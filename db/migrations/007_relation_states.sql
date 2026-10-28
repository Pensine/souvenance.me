-- Quality of ties: a relationship has a state, not just facts.
--
-- The graph could say "works at X since 2024" and close the edge the day it
-- is no longer true. It could not say that closeness has cooled, or that
-- tension has risen — yet that is precisely what makes a relationship a
-- relationship and not an administrative fact.
--
-- Two axes, for the same reason as the affective charge of a memory: a single
-- "good/bad relationship" slider would flatten situations that have nothing
-- to do with each other.
--
--   closeness   0 (distant) … 1 (intimate)    — the intensity of the tie
--   valence    -1 (tense) … +1 (warm)         — its colour
--
-- A family can be close AND tense; an old friend one no longer sees, distant
-- AND warm. With a single axis, the two look alike.
--
-- The state is not a mutable column on the edge: it is a sequence of dated
-- states. Overwriting the value would erase the evolution, which is exactly
-- what we are trying to capture. The past is closed (valid_to), not erased.
CREATE TABLE relation_states (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES entities(id),
    closeness REAL,
    valence REAL,
    note TEXT,                       -- what made it move, in one sentence
    confidence REAL NOT NULL DEFAULT 0.5,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,            -- NULL = current state
    source_event_ids BIGINT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT relation_states_closeness CHECK (
        closeness IS NULL OR (closeness >= 0.0 AND closeness <= 1.0)),
    CONSTRAINT relation_states_valence CHECK (
        valence IS NULL OR (valence >= -1.0 AND valence <= 1.0)),
    -- at least one axis filled in: an empty state teaches nothing
    CONSTRAINT relation_states_not_empty CHECK (
        closeness IS NOT NULL OR valence IS NOT NULL)
);

-- Only one current state per entity.
CREATE UNIQUE INDEX relation_states_current_idx
    ON relation_states(entity_id) WHERE valid_to IS NULL;
CREATE INDEX relation_states_entity_idx ON relation_states(entity_id, valid_from DESC);
