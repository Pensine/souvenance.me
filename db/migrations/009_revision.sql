-- A memory can stop being true, or drift away, without ever disappearing.
--
-- Two distinct gestures, as in a brain:
--   · REVISE: "what I knew in June is no longer true, because…".
--     The memory is closed (valid_to), possibly replaced by a new one
--     (superseded_by), and keeps the reason for the change. It remains
--     queryable as the past: "what did I think before?".
--   · ARCHIVE: the memory stays true but leaves current recall, like a distant
--     memory one no longer summons spontaneously. A question turned toward
--     the past finds it again.
--
-- Nothing is deleted: the event log remains the source of truth, and every
-- revision is first written there as an event.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS revised_at TIMESTAMPTZ;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS revision_note TEXT;

CREATE INDEX IF NOT EXISTS memories_archived_idx ON memories(archived_at)
    WHERE archived_at IS NOT NULL;
