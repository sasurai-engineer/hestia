"""The identity ceremonies (issue #40): passkeys only, sessions hashed at
rest, the bootstrap race serialized, invites redeemed exactly once, and the
gate refusing everything else."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import auth
from soft_webauthn import SoftWebauthnDevice


@pytest.fixture
def fresh_identity_world(database_url: str) -> str:
    """An identity-EMPTY world per test, so every bootstrap test means
    exactly what it says. Users are pinned by their audit rows (append-only
    by trigger), so an ordinary DELETE cannot make this world; the harness
    steps around the trigger as superuser for cleanup only — append-onlyness
    itself is module 006's test, not this one's. SQL instead of a full
    reset-and-remigrate because each remigrate is ~50 container execs, and
    fifteen of those per run wedges podman's conmon on macOS."""
    with psycopg.connect(database_url) as wipe:
        wipe.execute("SET session_replication_role = replica")
        wipe.execute("DELETE FROM audit_log WHERE user_id IS NOT NULL")
        for table in (
            "sessions",
            "auth_challenges",
            "auth_invites",
            "webauthn_credentials",
            "users",
        ):
            wipe.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed identifiers
        wipe.execute("SET session_replication_role = DEFAULT")
        wipe.commit()
    return database_url


@pytest.fixture
def bare_client(fresh_identity_world: str, conn: psycopg.Connection[Any]) -> Any:
    """A client with NO session — the ceremonies' own door."""
    from hestia_api.app import app

    with TestClient(app) as client:
        yield client


def _register(client: Any, handle: str, invite: str | None = None) -> SoftWebauthnDevice:
    """Run the full registration ceremony with a software authenticator;
    returns the device (it holds the credential for later logins)."""
    payload: dict[str, Any] = {"handle": handle}
    if invite is not None:
        payload["invite_code"] = invite
    opened = client.post("/auth/register/options", json=payload)
    assert opened.status_code == 200, opened.text
    body = opened.json()
    device = SoftWebauthnDevice()
    attestation = device.create({"publicKey": _for_device(body["options"])}, auth.rp_origin())
    attestation = _jsonable(attestation)
    done = client.post(
        "/auth/register",
        json={"challenge_id": body["challenge_id"], "credential": attestation},
    )
    assert done.status_code == 200, done.text
    return device


def _login(client: Any, device: SoftWebauthnDevice) -> Any:
    opened = client.post("/auth/login/options")
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assertion = device.get({"publicKey": _for_device(body["options"])}, auth.rp_origin())
    assertion = _jsonable(assertion)
    return client.post(
        "/auth/login",
        json={"challenge_id": body["challenge_id"], "credential": assertion},
    )


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _for_device(options: dict[str, Any]) -> dict[str, Any]:
    """The wire JSON carries base64url strings; soft-webauthn plays the
    browser's other half and wants the decoded buffers."""
    shaped = json.loads(json.dumps(options))  # deep copy
    shaped["challenge"] = _b64url_decode(options["challenge"])
    if "user" in shaped:
        shaped["user"]["id"] = _b64url_decode(options["user"]["id"])
    return shaped


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jsonable(value: Any) -> Any:
    """soft-webauthn returns raw bytes where the browser would send
    base64url; convert the whole structure to the wire shape."""
    if isinstance(value, bytes):
        return _b64url(value)
    if isinstance(value, dict):
        out = {k: _jsonable(v) for k, v in value.items()}
        # soft-webauthn's id is plain base64; the wire (and py_webauthn's
        # FIDO check) requires id == b64url(rawId).
        if "rawId" in out:
            out["id"] = out["rawId"]
        return out
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


class TestBootstrap:
    def test_the_first_owner_registers_without_an_invite_and_is_user0(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        device = _register(bare_client, "tai")
        me = bare_client.get("/auth/me").json()
        assert me["handle"] == "tai" and me["role"] == "owner"
        row = conn.execute("SELECT user_seq FROM users WHERE handle = 'tai'").fetchone()
        assert row is not None and row["user_seq"] == 1
        # The cookie now opens every door; without it, doors are shut.
        assert bare_client.get("/entities").status_code == 200
        # And the same device can log in usernameless.
        bare_client.cookies.clear()
        assert _login(bare_client, device).status_code == 200

    def test_the_second_bootstrap_loses_honestly(self, bare_client: Any) -> None:
        _register(bare_client, "tai")
        bare_client.cookies.clear()
        refused = bare_client.post("/auth/register/options", json={"handle": "impostor"})
        assert refused.status_code == 409
        assert "invite" in refused.json()["detail"]

    def test_the_first_user_carries_no_invite(self, bare_client: Any) -> None:
        # An invite code in an empty world is a confused client, not a favor.
        refused = bare_client.post(
            "/auth/register/options", json={"handle": "tai", "invite_code": "anything"}
        )
        assert refused.status_code == 409
        assert "needs no invite" in refused.json()["detail"]

    def test_the_bootstrap_race_loser_hears_it_at_verify(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        # Options are cheap and raceable; the advisory lock at VERIFY is
        # where two first-users serialize. Simulate the winner by SQL after
        # the loser's ceremony has opened.
        opened = bare_client.post("/auth/register/options", json={"handle": "loser"}).json()
        device = SoftWebauthnDevice()
        attestation = _jsonable(
            device.create({"publicKey": _for_device(opened["options"])}, auth.rp_origin())
        )
        conn.execute("INSERT INTO users (handle, role) VALUES ('winner', 'owner')")
        conn.commit()
        refused = bare_client.post(
            "/auth/register",
            json={"challenge_id": opened["challenge_id"], "credential": attestation},
        )
        assert refused.status_code == 409
        assert "already exists" in refused.json()["detail"]

    def test_the_gate_refuses_the_sessionless(self, bare_client: Any) -> None:
        assert bare_client.get("/entities").status_code == 401
        assert bare_client.get("/healthz").status_code == 200  # open by design


class TestInvites:
    def test_an_invite_is_redeemed_exactly_once(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        invite = bare_client.post("/auth/invites", json={"role": "owner"}).json()
        assert invite["code"]  # shown exactly once
        digest = conn.execute(
            "SELECT code_sha256 FROM auth_invites WHERE id = %s", (invite["id"],)
        ).fetchone()
        assert digest is not None
        assert bytes(digest["code_sha256"]) == hashlib.sha256(invite["code"].encode()).digest()
        bare_client.cookies.clear()
        _register(bare_client, "bri", invite=invite["code"])
        me = bare_client.get("/auth/me").json()
        assert me["handle"] == "bri" and me["role"] == "owner"
        # The same code again: the ceremony refuses at the door.
        bare_client.cookies.clear()
        again = bare_client.post(
            "/auth/register/options",
            json={"handle": "third", "invite_code": invite["code"]},
        )
        assert again.status_code == 409
        assert "already used" in again.json()["detail"]

    def test_a_resident_invite_carries_its_resident_and_cannot_invite(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        resident = conn.execute(
            "INSERT INTO residents (full_name) VALUES ('Jordan Tenant') RETURNING id::text"
        ).fetchone()
        conn.commit()
        assert resident is not None
        invite = bare_client.post(
            "/auth/invites", json={"role": "resident", "resident_id": resident["id"]}
        ).json()
        bare_client.cookies.clear()
        _register(bare_client, "jordan", invite=invite["code"])
        me = bare_client.get("/auth/me").json()
        assert me["role"] == "resident" and me["resident_id"] == resident["id"]
        # A resident is not an owner: inviting is refused.
        refused = bare_client.post("/auth/invites", json={"role": "owner"})
        assert refused.status_code == 403

    def test_a_taken_handle_is_refused_at_the_door(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        invite = bare_client.post("/auth/invites", json={"role": "owner"}).json()
        bare_client.cookies.clear()
        refused = bare_client.post(
            "/auth/register/options",
            json={"handle": "tai", "invite_code": invite["code"]},
        )
        assert refused.status_code == 409
        assert "taken" in refused.json()["detail"]

    def test_an_invite_snatched_mid_ceremony_is_refused(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        # The options step claims nothing; redemption is at verify, whole
        # and locked — so a code redeemed between the two steps loses.
        _register(bare_client, "tai")
        invite = bare_client.post("/auth/invites", json={"role": "owner"}).json()
        bare_client.cookies.clear()
        opened = bare_client.post(
            "/auth/register/options",
            json={"handle": "bri", "invite_code": invite["code"]},
        ).json()
        device = SoftWebauthnDevice()
        attestation = _jsonable(
            device.create({"publicKey": _for_device(opened["options"])}, auth.rp_origin())
        )
        conn.execute(
            """
            UPDATE auth_invites
            SET redeemed_at = now(),
                redeemed_by = (SELECT id FROM users WHERE handle = 'tai')
            WHERE id = %s
            """,
            (invite["id"],),
        )
        conn.commit()
        refused = bare_client.post(
            "/auth/register",
            json={"challenge_id": opened["challenge_id"], "credential": attestation},
        )
        assert refused.status_code == 409
        assert "someone faster" in refused.json()["detail"]


class TestCeremonyDefenses:
    def test_an_unknown_login_ceremony_is_refused(self, bare_client: Any) -> None:
        refused = bare_client.post(
            "/auth/login",
            json={"challenge_id": str(uuid.uuid4()), "credential": {}},
        )
        assert refused.status_code == 401
        assert "unknown, expired" in refused.json()["detail"]

    def test_a_tampered_assertion_fails_verification(self, bare_client: Any) -> None:
        device = _register(bare_client, "tai")
        bare_client.cookies.clear()
        opened = bare_client.post("/auth/login/options").json()
        assertion = _jsonable(
            device.get({"publicKey": _for_device(opened["options"])}, auth.rp_origin())
        )
        forged = bytearray(_b64url_decode(assertion["response"]["signature"]))
        forged[-1] ^= 0xFF
        assertion["response"]["signature"] = _b64url(bytes(forged))
        refused = bare_client.post(
            "/auth/login",
            json={"challenge_id": opened["challenge_id"], "credential": assertion},
        )
        assert refused.status_code == 401
        assert "failed verification" in refused.json()["detail"]

    def test_a_challenge_cannot_be_replayed(self, bare_client: Any) -> None:
        opened = bare_client.post("/auth/register/options", json={"handle": "tai"}).json()
        device = SoftWebauthnDevice()
        attestation = _jsonable(
            device.create({"publicKey": _for_device(opened["options"])}, auth.rp_origin())
        )
        first = bare_client.post(
            "/auth/register",
            json={"challenge_id": opened["challenge_id"], "credential": attestation},
        )
        assert first.status_code == 200
        bare_client.cookies.clear()
        replay = bare_client.post(
            "/auth/register",
            json={"challenge_id": opened["challenge_id"], "credential": attestation},
        )
        assert replay.status_code == 409
        assert "already used" in replay.json()["detail"]

    def test_a_foreign_origin_attestation_is_refused(self, bare_client: Any) -> None:
        opened = bare_client.post("/auth/register/options", json={"handle": "tai"}).json()
        device = SoftWebauthnDevice()
        attestation = _jsonable(
            device.create({"publicKey": _for_device(opened["options"])}, "https://evil.example")
        )
        refused = bare_client.post(
            "/auth/register",
            json={"challenge_id": opened["challenge_id"], "credential": attestation},
        )
        assert refused.status_code == 409
        assert "failed verification" in refused.json()["detail"]

    def test_a_regressed_sign_count_is_refused_at_the_database(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        conn.execute("UPDATE webauthn_credentials SET sign_count = 10")
        conn.commit()
        with pytest.raises(psycopg.errors.CheckViolation, match="cloned"):
            conn.execute("UPDATE webauthn_credentials SET sign_count = 3")
        conn.rollback()

    def test_an_unenrolled_passkey_cannot_log_in(self, bare_client: Any) -> None:
        _register(bare_client, "tai")
        bare_client.cookies.clear()
        stranger = SoftWebauthnDevice()
        opened = bare_client.post("/auth/login/options").json()
        # Enroll the stranger against a DIFFERENT rp locally so it can sign,
        # then present its assertion here.
        stranger.cred_init(auth.rp_id(), b"stranger")
        assertion = _jsonable(
            stranger.get({"publicKey": _for_device(opened["options"])}, auth.rp_origin())
        )
        refused = bare_client.post(
            "/auth/login",
            json={"challenge_id": opened["challenge_id"], "credential": assertion},
        )
        assert refused.status_code == 401
        assert "not enrolled" in refused.json()["detail"]


class TestSessions:
    def test_logout_revokes_and_the_cookie_dies(self, bare_client: Any) -> None:
        _register(bare_client, "tai")
        assert bare_client.get("/entities").status_code == 200
        bare_client.post("/auth/logout")
        assert bare_client.get("/entities").status_code == 401

    def test_an_expired_session_is_a_polite_401(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        conn.execute(
            """
            UPDATE sessions
            SET created_at = now() - interval '2 days',
                expires_at = now() - interval '1 minute'
            """
        )
        conn.commit()
        refused = bare_client.get("/entities")
        assert refused.status_code == 401
        assert "sign in again" in refused.json()["detail"]

    def test_the_management_door_wants_a_live_session(self, bare_client: Any) -> None:
        # /auth/ is an open prefix for the ceremonies, but the management
        # endpoints resolve the cookie themselves — absent or dead, 401.
        assert bare_client.post("/auth/invites", json={"role": "owner"}).status_code == 401
        assert bare_client.get("/auth/me").status_code == 401
        # Logout without a session is a no-op farewell, not an error.
        assert bare_client.post("/auth/logout").json() == {"status": "signed out"}
        bare_client.cookies.set(auth.SESSION_COOKIE, "not-a-session")
        dead_invite = bare_client.post("/auth/invites", json={"role": "owner"})
        assert dead_invite.status_code == 401
        assert "sign in again" in dead_invite.json()["detail"]
        dead_me = bare_client.get("/auth/me")
        assert dead_me.status_code == 401
        assert "sign in again" in dead_me.json()["detail"]

    def test_a_foreign_origin_mutation_is_refused_before_auth(self, bare_client: Any) -> None:
        _register(bare_client, "tai")
        refused = bare_client.post(
            "/entities",
            json={"name": "X", "kind": "llc"},
            headers={"origin": "https://evil.example"},
        )
        assert refused.status_code == 403

    def test_audit_rows_carry_the_authenticated_user(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        bare_client.post("/entities", json={"name": "Audited", "kind": "llc"})
        row = conn.execute(
            """
            SELECT a.actor, u.handle
            FROM audit_log a JOIN users u ON u.id = a.user_id
            WHERE a.action = 'entity.create'
            ORDER BY a.id DESC LIMIT 1
            """
        ).fetchone()
        assert row is not None
        assert row["actor"] == "user:tai" and row["handle"] == "tai"


class TestCredentials:
    def test_the_last_passkey_cannot_be_revoked(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        cred = conn.execute("SELECT id::text FROM webauthn_credentials").fetchone()
        assert cred is not None
        refused = bare_client.post(f"/auth/credentials/{cred['id']}/revoke")
        assert refused.status_code == 409
        assert "last passkey" in refused.json()["detail"]

    def test_a_spare_passkey_can_be_revoked_and_someone_elses_cannot(
        self, bare_client: Any, conn: psycopg.Connection[Any]
    ) -> None:
        _register(bare_client, "tai")
        me = bare_client.get("/auth/me").json()
        user = conn.execute("SELECT id::text FROM users WHERE handle = 'tai'").fetchone()
        assert user is not None and me["handle"] == "tai"
        spare = conn.execute(
            """
            INSERT INTO webauthn_credentials (user_id, credential_id, public_key)
            VALUES (%s, 'spare-cred', 'key-bytes') RETURNING id::text
            """,
            (user["id"],),
        ).fetchone()
        conn.commit()
        assert spare is not None
        revoked = bare_client.post(f"/auth/credentials/{spare['id']}/revoke")
        assert revoked.status_code == 204
        # A credential that is not yours (or does not exist) is refused.
        import uuid as uuid_module

        foreign = bare_client.post(f"/auth/credentials/{uuid_module.uuid4()}/revoke")
        assert foreign.status_code == 409
        assert "not yours" in foreign.json()["detail"]
