#!/usr/bin/env bash
# Put the provisioned toolchain on PATH for this shell.
#
# Version selection lives in ~/workspace/sasurai_assemble, which resolves the
# newest release satisfying every project's constraints and installs it
# keg-only so nothing global is relinked. This script holds no version numbers
# of its own -- it asks the resolver, and fails loudly if it cannot.
#
# Usage:  source scripts/env.sh

ASSEMBLE="${SASURAI_ASSEMBLE:-$HOME/workspace/sasurai_assemble}/assemble"

if [ -f "$ASSEMBLE" ] && [ -x "$ASSEMBLE" ]; then
  # Capture separately from eval so a failure is visible rather than becoming
  # an empty no-op that leaves the shell silently unprovisioned.
  # stderr must NOT join the string that gets eval'd. A diagnostic printed on a
  # successful run would otherwise be executed as shell in the user's
  # interactive session -- backticks in a warning became command substitution.
  _hestia_err="$(mktemp)"
  if _hestia_env="$(python3 "$ASSEMBLE" shellenv 2>"$_hestia_err")"; then
    eval "$_hestia_env"
    [ -s "$_hestia_err" ] && cat "$_hestia_err" >&2
  else
    printf 'hestia: sasurai_assemble could not resolve a toolchain:\n' >&2
    cat "$_hestia_err" >&2
  fi
  rm -f "$_hestia_err"
  unset _hestia_env _hestia_err
else
  printf 'hestia: sasurai_assemble not found at %s; using whatever is on PATH\n' \
    "$ASSEMBLE" >&2
fi

# The interpreter this repo's Python gates run under. Resolved, never pinned:
# whatever the provisioner put on PATH, falling back to the system one.
HESTIA_PYTHON="$(command -v python3 || true)"
export HESTIA_PYTHON
if [ -z "$HESTIA_PYTHON" ]; then
  printf 'hestia: no python3 on PATH\n' >&2
fi
