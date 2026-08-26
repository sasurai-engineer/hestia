"""Hestia simulation service.

Two halves, deliberately in one package:

- ``capex``: the Weibull Monte Carlo capital forecast — the probabilistic work
  that belongs in Python.
- ``finance``: independent reference implementations of the deterministic
  TypeScript engines, written against ``fractions``/``decimal`` rather than
  decimal.js. These generate the shared fixtures in
  ``packages/engines/fixtures`` and re-verify them in CI, so the two languages
  must agree to the cent or the build fails.
"""

__all__ = ["capex", "finance"]
