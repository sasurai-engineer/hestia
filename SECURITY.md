# Security Policy

## Reporting

Report vulnerabilities to **security@aletheiainstitute.ai**. Please do not open a
public issue. A principal reads every report.

Include what you can: affected component, reproduction, and impact. We will
acknowledge within three business days.

## Posture

- **Least privilege in CI.** Workflows declare `permissions: contents: read` and
  elevate per job. Checkouts run with `persist-credentials: false`.
- **No long-lived signing keys.** Release artifacts are signed with Sigstore
  cosign keyless (Fulcio certificates, Rekor transparency log).
- **Provenance.** Every release carries SLSA L3 provenance, verifiable with
  `slsa-verifier`.
- **SBOM.** A CycloneDX SBOM accompanies every release.
- **Dependencies.** Renovate opens CVE PRs immediately and on no schedule delay;
  a nightly sweep runs pnpm audit, OSV Scanner, and Trivy.
- **Secrets.** `scripts/config_audit.py` and gitleaks run on every push. Tracked
  `.env` files fail the build.
- **Money and tax data** are treated as sensitive: the ledger is event-sourced and
  bitemporal so that any figure can be reconstructed as of the date it was relied on.

## Scope

Supported: the `main` branch. This software is pre-release; no version has yet
been designated for production use.
