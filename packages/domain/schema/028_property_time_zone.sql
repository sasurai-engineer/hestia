-- ===========================================================================
--  028 — The property knows what 02:00 means where it stands (issue #58).
--
--  Time is local or it is wrong, and Kentucky and Tennessee both straddle a
--  zone line, so the state cannot decide — and per ADR 0003 it would not
--  get to. The zone is a PROPERTY fact: an IANA name, validated at the API
--  against the zoneinfo database (PostgreSQL cannot CHECK a set that ships
--  with the OS and moves), NULL an honest typed gap its consumers name —
--  the dispatch ranker, the notification digests, every deadline surface —
--  never a guess from the state.
-- ===========================================================================

ALTER TABLE properties ADD COLUMN time_zone TEXT;

COMMENT ON COLUMN properties.time_zone IS
  'IANA zone name (America/Chicago). Validated app-side against zoneinfo; '
  'NULL means the owner has not answered yet — consumers name the gap, '
  'nothing guesses from the state, because two of ours straddle zone lines.';
