-- ===========================================================================
--  030 — Identity: two named operators, and an audit trail that means it
--  (issue #40; designed and decided 2026-08-27 — passkeys only).
--
--  The API trusted an x-actor header; fine for localhost, worthless the
--  moment anything is exposed, and the audit trail was whatever the client
--  typed. The founder chose WebAuthn passkeys, no passwords (hashing
--  parameters and breach exposure are a permanent liability in a repo that
--  runs gitleaks and Semgrep over every push) and no magic links (there
--  was no email channel when this was decided).
--
--  Secrets discipline throughout, following document_blobs: the database
--  stores only the sha256 of session tokens and invite codes — a dump
--  opens no doors. Challenges live in a table, not a cache, because a
--  restart must not orphan a ceremony.
-- ===========================================================================

CREATE TYPE user_role AS ENUM ('owner', 'resident');

CREATE TABLE users (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- User0 is seq 1 forever: the bootstrap owner's number never moves.
  user_seq     BIGINT GENERATED ALWAYS AS IDENTITY,
  handle       TEXT NOT NULL UNIQUE CHECK (btrim(handle) <> ''),
  role         user_role NOT NULL,
  resident_id  UUID REFERENCES residents (id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- A resident login IS a resident; an owner login is not. Both directions.
  CONSTRAINT resident_logins_are_residents
    CHECK ((role = 'resident') = (resident_id IS NOT NULL)),
  CONSTRAINT one_login_per_resident UNIQUE (resident_id)
);

CREATE TABLE webauthn_credentials (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  credential_id  BYTEA NOT NULL UNIQUE,
  public_key     BYTEA NOT NULL,
  sign_count     BIGINT NOT NULL DEFAULT 0 CHECK (sign_count >= 0),
  label          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at   TIMESTAMPTZ,
  revoked_at     TIMESTAMPTZ
);

-- Sign-count monotonicity is enforced where it can be proven: a trigger,
-- because "the counter never decreases" is cross-row-in-time arithmetic no
-- CHECK can express. A regressing counter is a cloned-authenticator signal
-- and the update is REFUSED, loudly.
CREATE OR REPLACE FUNCTION refuse_sign_count_regression() RETURNS TRIGGER AS $$
BEGIN
  IF NEW.sign_count < OLD.sign_count THEN
    RAISE EXCEPTION 'sign count regressed from % to %: possible cloned authenticator',
      OLD.sign_count, NEW.sign_count
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER webauthn_sign_count_monotonic
  BEFORE UPDATE OF sign_count ON webauthn_credentials
  FOR EACH ROW EXECUTE FUNCTION refuse_sign_count_regression();

CREATE TABLE sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  -- Only the hash. The token itself exists once, in the Set-Cookie header.
  token_sha256 BYTEA NOT NULL UNIQUE CHECK (octet_length(token_sha256) = 32),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  revoked_at   TIMESTAMPTZ,
  CONSTRAINT sessions_expire_after_creation CHECK (expires_at > created_at)
);

CREATE TABLE auth_invites (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code_sha256  BYTEA NOT NULL UNIQUE CHECK (octet_length(code_sha256) = 32),
  role         user_role NOT NULL,
  resident_id  UUID REFERENCES residents (id),
  invited_by   UUID NOT NULL REFERENCES users (id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  redeemed_at  TIMESTAMPTZ,
  redeemed_by  UUID REFERENCES users (id),
  -- The invite decides what the login will be, so it obeys the same law.
  CONSTRAINT invite_role_matches_resident
    CHECK ((role = 'resident') = (resident_id IS NOT NULL)),
  CONSTRAINT redemption_is_whole
    CHECK ((redeemed_at IS NULL) = (redeemed_by IS NULL))
);

CREATE TABLE auth_challenges (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind        TEXT NOT NULL CHECK (kind IN ('register', 'login')),
  challenge   BYTEA NOT NULL,
  -- The handle a register ceremony was opened for: bound at options time so
  -- the verify step cannot be replayed under a different name.
  handle      TEXT,
  -- The user a register ceremony is for; login is usernameless.
  user_id     UUID REFERENCES users (id) ON DELETE CASCADE,
  invite_id   UUID REFERENCES auth_invites (id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ
);

-- The audit trail learns who, not just what the client claimed.
ALTER TABLE audit_log ADD COLUMN user_id UUID REFERENCES users (id);
COMMENT ON COLUMN audit_log.user_id IS
  'The authenticated user behind the actor string, when a session was '
  'present; NULL for system jobs (scheduler, webhooks) and pre-identity '
  'history.';
