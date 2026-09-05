"""Service configuration: environment in, typed values out, one place."""

from __future__ import annotations

import os


class ConfigurationError(RuntimeError):
    """A missing or malformed setting, named."""


def database_url() -> str:
    url = os.environ.get("HESTIA_DATABASE_URL", "")
    if not url:
        raise ConfigurationError("HESTIA_DATABASE_URL is not set; see .env.example for the shape")
    if not url.startswith(("postgresql://", "postgres://")):
        raise ConfigurationError("HESTIA_DATABASE_URL must be a postgresql:// URL")
    return url


def web_origin() -> str:
    """The browser origin allowed to call this API (the Next.js dev server by
    default). One origin, not a list: the deployment story is one owner's
    web app in front of one API."""
    return os.environ.get("HESTIA_WEB_ORIGIN", "http://localhost:3000")


def stripe_secret_key() -> str | None:
    """Present = payments enabled (test keys work before the LLC's live
    onboarding); absent = the collect endpoint says so instead of failing."""
    return os.environ.get("HESTIA_STRIPE_SECRET_KEY") or None


def stripe_webhook_secret() -> str:
    secret = os.environ.get("HESTIA_STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise ConfigurationError("HESTIA_STRIPE_WEBHOOK_SECRET is not set; see .env.example")
    return secret


def smtp_settings() -> tuple[str, int, str, str] | None:
    """(host, port, from, to) when the correspondent channel is configured;
    None otherwise — delivery then records to the ledger under 'log'. All
    four settings travel together: a partial configuration is a loud error,
    never a half-working channel."""
    host = os.environ.get("HESTIA_SMTP_HOST", "").strip()
    sender = os.environ.get("HESTIA_SMTP_FROM", "").strip()
    recipient = os.environ.get("HESTIA_NOTIFY_TO", "").strip()
    if not any((host, sender, recipient)):
        return None
    if not all((host, sender, recipient)):
        raise ConfigurationError(
            "HESTIA_SMTP_HOST, HESTIA_SMTP_FROM and HESTIA_NOTIFY_TO travel "
            "together; set all three or none (see .env.example)"
        )
    raw_port = os.environ.get("HESTIA_SMTP_PORT", "587").strip()
    try:
        port = int(raw_port)
    except ValueError as error:
        raise ConfigurationError(
            f"HESTIA_SMTP_PORT must be an integer, received {raw_port!r}"
        ) from error
    return host, port, sender, recipient
