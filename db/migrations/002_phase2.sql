-- Phase 2: voiceprints, strengthened graph

-- Voiceprints (ECAPA-TDNN, 192 dims) — enrolment is an explicit act (§8)
CREATE TABLE voiceprints (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES entities(id),
    embedding VECTOR(192) NOT NULL,
    sample_note TEXT,              -- provenance of the enrolment sample
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Graph: clean upsert of entities
CREATE UNIQUE INDEX entities_name_kind_idx ON entities (lower(name), kind);
CREATE INDEX relations_subject_idx ON relations (subject_id, predicate)
    WHERE valid_to IS NULL;

-- Full bi-temporality: when did the graph LEARN the fact
-- (valid_from/valid_to = world time; created_at/invalidated_at = system time)
ALTER TABLE relations
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN invalidated_at TIMESTAMPTZ;
