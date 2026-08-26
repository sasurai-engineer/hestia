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
