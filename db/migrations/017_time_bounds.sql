-- Bounded dating: when did it happen, as far as the deposits can say.
--
-- "The kayak has not arrived yet" (3 March) and "the kayak is already here"
-- (11 March) do not date the arrival; together they bound it. A memory's
-- event time is therefore stored as bounds, each backed by its own quote:
--   earliest  the event did not happen before this date ("not yet")
--   latest    it had happened by this date ("already", "since", "by then")
-- An exact date is earliest = latest. Admission is decided in code
-- (pensine/dating.py): the excerpt must be found in its deposit and carry a
-- date expression or a temporal relation; the date is computed from the
-- expression, or taken from the deposit's own timestamp (basis
-- 'deposit_time'), never from the model.
--
-- Why on memories and not on graph edges: the evidence (excerpts, source
-- deposits, the integrity cascade, crypto-shredding) already lives on
-- memories; edges carry no quote. A bound is a piece of evidence about the
-- memory's fact, so it sits next to the memory's other evidence.
--
-- Memories about one fact share an `event_key` (with the same subject
-- entity, migration 016): their bounds pool into one interval, computed at
-- read time (dating.for_memories), never stored, so it cannot drift from the
-- quotes it rests on.
CREATE TABLE IF NOT EXISTS memory_time_bounds (
    id BIGSERIAL PRIMARY KEY,
    memory_id BIGINT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    earliest DATE,                       -- not before (inclusive)
    latest DATE,                         -- not after (inclusive)
    excerpt TEXT NOT NULL,               -- quoted from the source deposit
    source_event_id BIGINT NOT NULL REFERENCES events(id),
    basis TEXT NOT NULL CHECK (basis IN ('excerpt_date', 'deposit_time')),
    cue TEXT,                            -- the expression or relation found
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (earliest IS NOT NULL OR latest IS NOT NULL),
    CHECK (earliest IS NULL OR latest IS NULL OR earliest <= latest)
);
CREATE INDEX IF NOT EXISTS memory_time_bounds_memory_idx ON memory_time_bounds (memory_id);
CREATE INDEX IF NOT EXISTS memory_time_bounds_source_idx ON memory_time_bounds (source_event_id);

ALTER TABLE memories ADD COLUMN IF NOT EXISTS event_key TEXT;
CREATE INDEX IF NOT EXISTS memories_event_key_idx ON memories (event_key)
    WHERE event_key IS NOT NULL;
