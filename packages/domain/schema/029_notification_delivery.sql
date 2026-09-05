-- ===========================================================================
--  029 — The correspondent channel's delivery ledger (issue #38).
--
--  VISION P3 makes the notification channel a primary surface, not a
--  delivery seam: for most of the year Hestia is a correspondent, and what
--  it sends must be as auditable as what it books. This table is that
--  ledger — one row per (deadline, reminder step), which is what makes "a
--  deadline inside its reminder window produces exactly one digest entry
--  per schedule step" a database fact instead of a hope.
--
--  The three standing urgency classes are the vision's law, typed here so
--  no message can ship without one: interrupt_now is reserved (refusal 13:
--  the first false interrupt is a covenant breach of its own kind),
--  next_session waits in the digest, on_record informs the ledger only.
--
--  Delivery failures are the one place this ledger updates in place: a
--  failed send keeps its row and retries into it (attempts counted, last
--  error kept), because the identity being protected is the MESSAGE — one
--  per deadline per step — not the attempt. Nothing here is money.
-- ===========================================================================

CREATE TYPE urgency_class AS ENUM ('interrupt_now', 'next_session', 'on_record');

CREATE TYPE delivery_status AS ENUM ('sent', 'logged', 'failed');

CREATE TABLE notifications (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deadline_id      UUID NOT NULL REFERENCES deadlines (id) ON DELETE CASCADE,
  -- Which reminderSchedule step this message is: the lead, in days, from
  -- the deadline's due date. One message per step, forever.
  lead_days        SMALLINT NOT NULL CHECK (lead_days >= 0),
  urgency          urgency_class NOT NULL,
  channel          TEXT NOT NULL,            -- 'email' | 'log'
  recipient        TEXT,                     -- NULL when channel = 'log'
  subject          TEXT NOT NULL,
  body             TEXT NOT NULL,
  status           delivery_status NOT NULL,
  attempts         SMALLINT NOT NULL DEFAULT 1 CHECK (attempts >= 1),
  last_error       TEXT,
  delivered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT one_message_per_step UNIQUE (deadline_id, lead_days),
  CONSTRAINT failed_says_why
    CHECK (status <> 'failed' OR last_error IS NOT NULL),
  CONSTRAINT email_names_its_recipient
    CHECK (channel <> 'email' OR recipient IS NOT NULL)
);

COMMENT ON TABLE notifications IS
  'The correspondent channel''s ledger (VISION P3): one row per (deadline, '
  'reminder step). Failures retry INTO their row — the protected identity '
  'is the message, not the attempt.';
COMMENT ON COLUMN notifications.urgency IS
  'The vision''s standing classes. interrupt_now is reserved; a false '
  'interrupt is a covenant breach of its own kind (refusal 13).';
