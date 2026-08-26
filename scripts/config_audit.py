#!/usr/bin/env python3
"""Configuration contract audit.

Catches the class of mistake that never shows up in a unit test and never
fails a build until it is already public: a credential committed to the
repository, a tracked ``.env``, or an environment variable the code reads
but no one documented.

Runs against a checkout. Requires no running stack, no network, and no
third-party packages. Exit code 0 means clean; 1 means findings.

    python3 scripts/config_audit.py [--root .] [--quiet]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Files we never scan for secrets: lockfiles and vendored trees are noise.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".turbo",
    "reports",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".stryker-tmp",
}
SKIP_FILES = {"pnpm-lock.yaml", "package-lock.json", "uv.lock", "Cargo.lock"}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".zip",
    ".gz",
    ".map",
}

# Literal credentials that must never reappear. The first two are inherited
# lab credentials from the ai_services stack; they are burned and must stay
# out of this repository permanently.
FORBIDDEN_LITERALS = (
    "S0crates-ChangeMe-2026!",
    "admin:socrates",
)

# Credential shapes. Each entry is (rule, pattern, heuristic).
#
# High-confidence patterns (heuristic=False) match a shape that is a
# credential and nothing else, so a placeholder-looking value never excuses
# them -- AWS's own documentation key "AKIAIOSFODNN7EXAMPLE" is still a
# finding, because a scanner that trusts the word "example" can be defeated
# by naming a real key "example".
#
# Heuristic patterns (heuristic=True) infer intent from a variable name and
# therefore do respect the placeholder allowlist; without it they would fire
# on every config template and train people to ignore this tool.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), False),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), False),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), False),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), False),
    ("Stripe secret key", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}\b"), False),
    ("model provider API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"), False),
    ("OpenAI API key", re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{20,}\b"), False),
    (
        "private key block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        False,
    ),
    (
        "JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        False,
    ),
    (
        "hardcoded credential assignment",
        re.compile(
            r"""(?ix)
            (?:^|[^A-Za-z0-9_])
            # Any number of leading name segments, so AWS_SECRET_ACCESS_KEY
            # matches on ACCESS_KEY and DB_PASSWORD on PASSWORD. A single
            # optional segment was not enough, and a leading \b matched none of
            # them at all because `_` is a word character.
            (?:[A-Za-z0-9]+[_.-])*
            (?:password|passwd|pwd|secret|api[_-]?key|apikey|credential
               |private[_-]?key|access[_-]?key|token|auth)
            \s*[:=]\s*
            (?:['"][^'"\s${}<>]{8,}['"]|[^'"\s${}<>,;)\]]{8,})
            """
        ),
        True,
    ),
)


# Values that declare intent rather than carry a secret. Applied only to the
# heuristic pattern above.
def _is_placeholder(value_text: str) -> bool:
    """Whether a matched value is a stand-in rather than a credential.

    Substring matching was the bug: a genuine seventeen-character key
    containing "xxx" anywhere suppressed itself. A placeholder has to account
    for most of what it is standing in for, so the match is measured against
    the length of the value.
    """
    stripped = value_text.strip().strip("\"'").strip()
    if not stripped:
        return True
    found = ALLOWED_VALUE_HINTS.search(stripped)
    if found is None:
        return False
    return len(found.group(0)) * 2 >= len(stripped)


ALLOWED_VALUE_HINTS = re.compile(
    r"(?i)(change[_-]?me|example|placeholder|redacted|dummy|sample|your[_-]|xxx+|\.\.\.|"
    r"process\.env|os\.environ|getenv|<[^>]+>|\$\{)"
)

ENV_REF = re.compile(
    r"""(?x)
    (?: process\.env\.(?P<js_dot>[A-Za-z_][A-Za-z0-9_]*) )
    | (?: process\.env\[['"](?P<js_idx>[A-Za-z_][A-Za-z0-9_]*)['"]\] )
    | (?: os\.environ(?:\.get)?\(?\[?['"](?P<py>[A-Za-z_][A-Za-z0-9_]*)['"] )
    | (?: os\.getenv\(['"](?P<py_get>[A-Za-z_][A-Za-z0-9_]*)['"] )
    """
)

# Variables provided by the platform, not by our own configuration.
AMBIENT_ENV = {
    "NODE_ENV",
    "CI",
    "PATH",
    "HOME",
    "PWD",
    "TZ",
    "PORT",
    "LANG",
    "GITHUB_TOKEN",
    "GITHUB_SHA",
    "GITHUB_REF",
    "GITHUB_ACTIONS",
    "npm_lifecycle_event",
    "TURBO_TELEMETRY_DISABLED",
    "DO_NOT_TRACK",
    "NODE_OPTIONS",
    "VERCEL",
    "VERCEL_ENV",
    "NEXT_RUNTIME",
}


# This scanner and its tests necessarily contain the credential shapes they
# hunt for. Exempting them by resolved path rather than by a repo-root-relative
# string means the exemption survives any --root, and covers the fixtures --
# which live in the tests directory beside this file and were previously
# scanned, producing eleven findings on the first commit and a permanently red
# security gate.
_SELF = Path(__file__).resolve()
_SELF_TESTS = _SELF.parent / "tests"


def is_own_source(path: Path) -> bool:
    """True for this scanner and its own test fixtures."""
    resolved = path.resolve()
    if resolved == _SELF:
        return True
    return _SELF_TESTS in resolved.parents


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  [{self.rule}] {self.detail}"


def tracked_files(root: Path) -> tuple[list[Path], bool]:
    """The files git actually tracks, and whether git could answer.

    Returns ``(paths, from_index)``. An *empty* index is a real answer -- a
    repository with no commits yet -- and must not be mistaken for a git
    failure. Falling through to a working-tree walk in that case inverts the
    tool's meaning from "what is committed" to "what is on disk", which makes
    a correctly-gitignored local ``.env`` look like a committed secret.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
        return [root / n for n in out.split("\0") if n], True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in root.rglob("*") if p.is_file()], False


def scannable(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    # Directories only: rel.parts ends with the file's own name, so testing the
    # whole tuple silently excluded any file named `build`, `dist` or `target`.
    if any(part in SKIP_DIRS for part in rel.parts[:-1]):
        return False
    return not (path.name in SKIP_FILES or path.suffix.lower() in SKIP_SUFFIXES)


_WINDOW = 4096
_OVERLAP = 256


def _windows(line: str) -> list[str]:
    """Split an over-long line into overlapping windows.

    The overlap is wider than the longest credential shape, so a key straddling
    a window boundary still matches in one of them.
    """
    if len(line) <= _WINDOW:
        return [line]
    step = _WINDOW - _OVERLAP
    return [line[start : start + _WINDOW] for start in range(0, len(line), step)]


def read_lines(path: Path) -> list[str]:
    """Decode leniently and split only on newlines.

    Returning [] for a file that is not valid UTF-8 makes it invisible to every
    rule while the audit still reports "clean" -- a UTF-16 .env carrying a live
    key would pass. Replacement characters keep the ASCII credential shapes
    intact and still match.

    str.splitlines() additionally breaks on \x0b, \x0c, \x85, \u2028 and
    \u2029, which git and every editor treat as ordinary characters, so a
    reported line number would not match the file. Split on newlines only.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    return raw.decode("utf-8", errors="replace").split("\n")


def check_tracked_env_files(files: list[Path], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        name = path.name
        if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
            findings.append(
                Finding(
                    str(path.relative_to(root)),
                    0,
                    "tracked-env-file",
                    "environment files must never be committed; commit .env.example instead",
                )
            )
    return findings


def check_secrets(files: list[Path], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        rel = str(path.relative_to(root))
        if is_own_source(path):
            continue
        for lineno, line in enumerate(read_lines(path), start=1):
            for literal in FORBIDDEN_LITERALS:
                if literal in line:
                    findings.append(
                        Finding(
                            rel,
                            lineno,
                            "forbidden-credential",
                            "a known-burned credential appears on this line",
                        )
                    )
            if "config-audit: allow" in line:
                continue
            # A long line is scanned in overlapping windows rather than skipped.
            # Skipping it meant a committed minified bundle, a single-line JSON
            # config or a one-line .env carrying a live key passed the gate
            # green -- and the comment that justified it was wrong, because the
            # literal scan above covers two known literals, not the nine key
            # shapes below.
            segments = _windows(line)
            for rule, pattern, heuristic in SECRET_PATTERNS:
                match = next(
                    (found for found in (pattern.search(seg) for seg in segments) if found),
                    None,
                )
                if not match:
                    continue
                if heuristic:
                    # Check the value, not the whole match: the variable name is
                    # part of group(0), so a name containing "example" or
                    # "sample" used to suppress a real value beside it.
                    positions = [
                        i for i in (match.group(0).find("="), match.group(0).find(":")) if i >= 0
                    ]
                    # The FIRST separator: a value may itself contain ':' or '=',
                    # and splitting on the last one would leave part of the value
                    # on the name side where the allowlist cannot see it.
                    value_text = (
                        match.group(0)[min(positions) + 1 :] if positions else match.group(0)
                    )
                    if _is_placeholder(value_text):
                        continue
                # The rule and the location, never the value. Echoing the match
                # would republish a leaked key into a public CI log.
                findings.append(
                    Finding(
                        rel,
                        lineno,
                        "secret",
                        f"{rule} (matched {len(match.group(0))} characters; value withheld)",
                    )
                )
    return findings


def parse_env_example(path: Path) -> tuple[set[str], list[Finding]]:
    keys: set[str] = set()
    findings: list[Finding] = []
    if not path.exists():
        return keys, findings
    seen: dict[str, int] = {}
    for lineno, raw in enumerate(read_lines(path), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key in seen:
            findings.append(
                Finding(
                    path.name,
                    lineno,
                    "duplicate-env-key",
                    f"{key} already defined on line {seen[key]}",
                )
            )
        seen[key] = lineno
        keys.add(key)
    return keys, findings


def check_env_drift(files: list[Path], root: Path, documented: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        if path.suffix not in {".ts", ".tsx", ".js", ".mjs", ".py"}:
            continue
        rel = str(path.relative_to(root))
        if is_own_source(path):
            continue
        for lineno, line in enumerate(read_lines(path), start=1):
            for match in ENV_REF.finditer(line):
                name = next((g for g in match.groups() if g), None)
                if not name or name in AMBIENT_ENV or name in documented:
                    continue
                findings.append(
                    Finding(
                        rel,
                        lineno,
                        "undocumented-env",
                        f"{name} is read here but absent from .env.example",
                    )
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    candidates, from_index = tracked_files(root)
    files = [p for p in candidates if p.is_file() and scannable(p, root)]

    documented, findings = parse_env_example(root / ".env.example")
    findings += check_tracked_env_files(files, root)
    findings += check_secrets(files, root)
    findings += check_env_drift(files, root, documented)

    findings.sort(key=lambda f: (f.path, f.line, f.rule))

    if findings:
        print(f"config audit: {len(findings)} finding(s)\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nSuppress an intentional match with a trailing `config-audit: allow`.",
            file=sys.stderr,
        )
        return 1

    if from_index and not files:
        # A gate that scans nothing must say so. Reporting "clean" over an empty
        # file set is indistinguishable from reporting it over a clean one.
        print(
            "config audit: git tracks no files here, so nothing was audited. "
            "Commit first, or pass --root at a checked-out tree.",
            file=sys.stderr,
        )
        return 1

    if not args.quiet:
        scope = "tracked" if from_index else "on-disk (git unavailable)"
        print(
            f"config audit: clean ({len(files)} {scope} files, {len(documented)} documented vars)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
