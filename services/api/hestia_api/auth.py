"""Identity: passkeys only, sessions in the database, secrets never at rest
(issue #40; the design the founder decided 2026-08-27).

No passwords — hashing parameters and breach exposure are a permanent
liability. No magic links — a login must not depend on a channel that may
be unconfigured. WebAuthn passkeys, usernameless at login (discoverable
credentials), with every ceremony's challenge in a table rather than a
cache so a restart orphans nothing.

The document_blobs discipline applies to every secret: the database holds
only sha256 digests of session tokens and invite codes. The token exists
once, in the Set-Cookie header; the invite code exists once, in the
response that created it. A database dump opens no doors.

First run: while zero users exist, registration needs no invite — two
racing bootstraps serialize on an advisory lock and yield one User0 and
one 409. Everyone after joins by one-time invite, redeemed compare-and-set
so the race loser learns the truth instead of sharing a code.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import secrets
from typing import Any

import psycopg
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json_dict
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from hestia_api import config

Conn = psycopg.Connection[dict[str, Any]]

SESSION_COOKIE = "hestia_session"
SESSION_TTL = dt.timedelta(days=30)
CHALLENGE_TTL = dt.timedelta(minutes=10)
INVITE_TTL = dt.timedelta(days=7)
# 'HESTIA40' — the bootstrap race serializes here.
BOOTSTRAP_LOCK_KEY = 0x4845535449413430


def rp_id() -> str:
    """The WebAuthn relying-party id. localhost today; every credential is
    re-enrolled when real hosting lands (#33) — a known, accepted cost."""
    return os.environ.get("HESTIA_RP_ID", "localhost").strip() or "localhost"


def rp_origin() -> str:
    return os.environ.get("HESTIA_RP_ORIGIN", "").strip() or config.web_origin()


def _sha256(value: str | bytes) -> bytes:
    raw = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(raw).digest()


class AuthError(Exception):
    """A ceremony that must not proceed; the message is safe to show."""


class NotAuthenticated(Exception):
    pass


class Principal(BaseModel):
    user_id: str
    user_seq: int
    handle: str
    role: str
    resident_id: str | None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def create_session(conn: Conn, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO sessions (user_id, token_sha256, expires_at)
        VALUES (%s, %s, now() + %s)
        """,
        (user_id, _sha256(token), SESSION_TTL),
    )
    return token


def session_principal(conn: Conn, token: str) -> Principal:
    row = conn.execute(
        """
        SELECT u.id::text AS user_id, u.user_seq, u.handle, u.role::text,
               u.resident_id::text AS resident_id
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_sha256 = %s AND s.revoked_at IS NULL AND s.expires_at > now()
        """,
        (_sha256(token),),
    ).fetchone()
    if row is None:
        raise NotAuthenticated
    return Principal(**row)


def revoke_session(conn: Conn, token: str) -> None:
    conn.execute(
        "UPDATE sessions SET revoked_at = now() WHERE token_sha256 = %s AND revoked_at IS NULL",
        (_sha256(token),),
    )


# ---------------------------------------------------------------------------
# Registration — bootstrap or invite
# ---------------------------------------------------------------------------


class RegisterOptionsIn(BaseModel):
    handle: str = Field(min_length=1, max_length=80)
    invite_code: str | None = None


class RegisterVerifyIn(BaseModel):
    challenge_id: str
    credential: dict[str, Any]  # the browser's PublicKeyCredential JSON
    label: str | None = Field(default=None, max_length=120)


def _user_count(conn: Conn) -> int:
    row = conn.execute("SELECT count(*) AS n FROM users").fetchone()
    return int(row["n"]) if row else 0


def _claim_invite(conn: Conn, code: str) -> dict[str, Any]:
    """Look, but do not redeem: redemption is compare-and-set at VERIFY time
    so an abandoned options call burns nothing."""
    row = conn.execute(
        """
        SELECT id::text, role::text, resident_id::text AS resident_id
        FROM auth_invites
        WHERE code_sha256 = %s AND redeemed_at IS NULL AND expires_at > now()
        """,
        (_sha256(code),),
    ).fetchone()
    if row is None:
        raise AuthError("that invite is unknown, expired, or already used")
    return row


def register_options(conn: Conn, body: RegisterOptionsIn) -> dict[str, Any]:
    invite_id: str | None = None
    if _user_count(conn) == 0:
        # First run: no invite needed; the VERIFY step takes the bootstrap
        # lock, so options stay cheap and raceable.
        if body.invite_code is not None:
            raise AuthError("the first user needs no invite")
    else:
        if body.invite_code is None:
            raise AuthError("registration is by invite")
        invite_id = _claim_invite(conn, body.invite_code)["id"]
    taken = conn.execute("SELECT 1 AS x FROM users WHERE handle = %s", (body.handle,)).fetchone()
    if taken is not None:
        raise AuthError("that handle is taken")
    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name="Hestia",
        user_name=body.handle,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    challenge = conn.execute(
        """
        INSERT INTO auth_challenges (kind, challenge, handle, invite_id, expires_at)
        VALUES ('register', %s, %s, %s, now() + %s) RETURNING id::text
        """,
        (options.challenge, body.handle, invite_id, CHALLENGE_TTL),
    ).fetchone()
    assert challenge is not None
    return {
        "challenge_id": challenge["id"],
        "handle": body.handle,
        "options": options_to_json_dict(options),
    }


def register_verify(conn: Conn, body: RegisterVerifyIn) -> str:
    """Verify the attestation, create the user (User0 under the bootstrap
    lock, or by CAS-redeeming the invite), store the credential, open a
    session. Returns the session token."""
    challenge = conn.execute(
        """
        UPDATE auth_challenges SET consumed_at = now()
        WHERE id = %s AND kind = 'register' AND consumed_at IS NULL
          AND expires_at > now()
        RETURNING challenge, handle, invite_id::text AS invite_id
        """,
        (body.challenge_id,),
    ).fetchone()
    if challenge is None or challenge["handle"] is None:
        raise AuthError("that ceremony is unknown, expired, or already used")
    handle = challenge["handle"]
    try:
        verification = verify_registration_response(
            credential=body.credential,
            expected_challenge=bytes(challenge["challenge"]),
            expected_origin=rp_origin(),
            expected_rp_id=rp_id(),
        )
    except (InvalidRegistrationResponse, ValueError) as error:
        raise AuthError("the authenticator's answer failed verification") from error
    role, resident_id = "owner", None
    if challenge["invite_id"] is None:
        # The bootstrap: two racers serialize here; the loser sees users > 0.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (BOOTSTRAP_LOCK_KEY,))
        if _user_count(conn) != 0:
            raise AuthError("the first user already exists; ask them for an invite")
    else:
        # Lock, then redeem WHOLE after the user exists: redemption_is_whole
        # forbids a half-redeemed row, and the row lock keeps the
        # compare-and-set honest — the race loser blocks here and then
        # finds redeemed_at set.
        invite = conn.execute(
            """
            SELECT role::text, resident_id::text AS resident_id
            FROM auth_invites
            WHERE id = %s AND redeemed_at IS NULL AND expires_at > now()
            FOR UPDATE
            """,
            (challenge["invite_id"],),
        ).fetchone()
        if invite is None:
            raise AuthError("that invite was redeemed by someone faster")
        role, resident_id = invite["role"], invite["resident_id"]
    user = conn.execute(
        """
        INSERT INTO users (handle, role, resident_id)
        VALUES (%s, %s, %s) RETURNING id::text
        """,
        (handle, role, resident_id),
    ).fetchone()
    assert user is not None
    if challenge["invite_id"] is not None:
        conn.execute(
            """
            UPDATE auth_invites SET redeemed_at = now(), redeemed_by = %s
            WHERE id = %s AND redeemed_at IS NULL
            """,
            (user["id"], challenge["invite_id"]),
        )
    conn.execute(
        """
        INSERT INTO webauthn_credentials
          (user_id, credential_id, public_key, sign_count, label)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user["id"],
            verification.credential_id,
            verification.credential_public_key,
            verification.sign_count,
            body.label,
        ),
    )
    return create_session(conn, user["id"])


# ---------------------------------------------------------------------------
# Login — usernameless, discoverable credentials
# ---------------------------------------------------------------------------


class LoginVerifyIn(BaseModel):
    challenge_id: str
    credential: dict[str, Any]


def login_options(conn: Conn) -> dict[str, Any]:
    options = generate_authentication_options(
        rp_id=rp_id(),
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=[],  # usernameless: the authenticator discovers
    )
    challenge = conn.execute(
        """
        INSERT INTO auth_challenges (kind, challenge, expires_at)
        VALUES ('login', %s, now() + %s) RETURNING id::text
        """,
        (options.challenge, CHALLENGE_TTL),
    ).fetchone()
    assert challenge is not None
    return {"challenge_id": challenge["id"], "options": options_to_json_dict(options)}


def login_verify(conn: Conn, body: LoginVerifyIn) -> str:
    challenge = conn.execute(
        """
        UPDATE auth_challenges SET consumed_at = now()
        WHERE id = %s AND kind = 'login' AND consumed_at IS NULL
          AND expires_at > now()
        RETURNING challenge
        """,
        (body.challenge_id,),
    ).fetchone()
    if challenge is None:
        raise AuthError("that ceremony is unknown, expired, or already used")
    raw_id = body.credential.get("rawId") or body.credential.get("id") or ""
    credential_id = base64.urlsafe_b64decode(raw_id + "=" * (-len(raw_id) % 4))
    stored = conn.execute(
        """
        SELECT c.id::text, c.user_id::text AS user_id, c.public_key, c.sign_count
        FROM webauthn_credentials c
        WHERE c.credential_id = %s AND c.revoked_at IS NULL
        FOR UPDATE
        """,
        (credential_id,),
    ).fetchone()
    if stored is None:
        raise AuthError("that passkey is not enrolled here")
    try:
        verification = verify_authentication_response(
            credential=body.credential,
            expected_challenge=bytes(challenge["challenge"]),
            expected_origin=rp_origin(),
            expected_rp_id=rp_id(),
            credential_public_key=bytes(stored["public_key"]),
            credential_current_sign_count=int(stored["sign_count"]),
        )
    except (InvalidAuthenticationResponse, ValueError) as error:
        raise AuthError("the authenticator's answer failed verification") from error
    # The monotonicity trigger backs this at the database; a regressing
    # counter raises there even if a future edit here forgets.
    conn.execute(
        """
        UPDATE webauthn_credentials
        SET sign_count = %s, last_used_at = now()
        WHERE id = %s
        """,
        (verification.new_sign_count, stored["id"]),
    )
    return create_session(conn, stored["user_id"])


# ---------------------------------------------------------------------------
# Invites and credential management
# ---------------------------------------------------------------------------


class InviteIn(BaseModel):
    role: str = Field(pattern=r"^(owner|resident)$")
    resident_id: str | None = None


class InviteOut(BaseModel):
    id: str
    code: str  # shown exactly once
    role: str
    expires_at: dt.datetime


def create_invite(conn: Conn, principal: Principal, body: InviteIn) -> InviteOut:
    code = secrets.token_urlsafe(9)
    row = conn.execute(
        """
        INSERT INTO auth_invites (code_sha256, role, resident_id, invited_by, expires_at)
        VALUES (%s, %s, %s, %s, now() + %s)
        RETURNING id::text, expires_at
        """,
        (_sha256(code), body.role, body.resident_id, principal.user_id, INVITE_TTL),
    ).fetchone()
    assert row is not None
    return InviteOut(id=row["id"], code=code, role=body.role, expires_at=row["expires_at"])


def revoke_credential(conn: Conn, principal: Principal, credential_id: str) -> None:
    """Refuses to revoke the caller's LAST usable credential: a login that
    can lock itself out permanently is a support incident, not a feature."""
    rows = conn.execute(
        """
        SELECT id::text FROM webauthn_credentials
        WHERE user_id = %s AND revoked_at IS NULL
        FOR UPDATE
        """,
        (principal.user_id,),
    ).fetchall()
    mine = {r["id"] for r in rows}
    if credential_id not in mine:
        raise AuthError("that credential is not yours to revoke")
    if len(mine) == 1:
        raise AuthError("refusing to revoke your last passkey; enroll another first")
    conn.execute(
        "UPDATE webauthn_credentials SET revoked_at = now() WHERE id = %s",
        (credential_id,),
    )
