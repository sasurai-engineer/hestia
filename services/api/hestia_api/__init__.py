"""The Hestia API service.

The first consumer-facing seam: a typed OpenAPI contract over the ledger, the
audit-log write path every mutation flows through, and the deadline sweep that
turns portfolio facts into rows the calendar can alert on. psycopg hands
NUMERIC back as Decimal — money never becomes a float on the way through here
either.
"""

__all__ = ["app", "calendar", "config", "db", "sweep"]
