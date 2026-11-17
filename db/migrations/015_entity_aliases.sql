-- Identity claims: "my sister" and "Priya" are the same person — says who?
--
-- A memory graph that merges two mentions into one entity takes an identity
-- decision. Most systems take it silently (an LLM returns "duplicate of #12")
-- and keep neither the reason nor a way back. Here each such decision is a
-- CLAIM, stored with the excerpt of the deposit that proves it and a
-- confidence, and it can be retracted.
--
-- Admission is decided in code (pensine/identity.py): the excerpt must be
-- found in the source deposit AND name both the alias and the canonical name
-- ("my sister Priya", "Priya, ma sœur"), or the deposit metadata must tie
-- them (sender / author / forwarder). Anything else stays 'pending': kept for
-- inspection, never used to resolve a mention.
--
-- Append-only in spirit: a claim is never edited and never deleted by the
-- engine. Retracting closes it (status, retracted_at, retract_reason); the
-- edges that were attached through it are reported, not rewritten. The only
-- DELETE is crypto-shredding of its source deposit (pensine/shred.py).
CREATE TABLE IF NOT EXISTS entity_aliases (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES entities(id),
    alias TEXT NOT NULL,                 -- as written: 'my sister', 'Pri'
    alias_norm TEXT NOT NULL,            -- identity.norm(alias): lookup key
    alias_kind TEXT NOT NULL CHECK (alias_kind IN ('name', 'role')),
    role_of_owner TEXT,                  -- 'sister', 'colleague'… (role aliases)
    excerpt TEXT NOT NULL,               -- quoted from the source deposit
    source_event_id BIGINT REFERENCES events(id),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'retracted')),
    admission TEXT NOT NULL,             -- 'excerpt' | 'metadata' | why it is pending
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retracted_at TIMESTAMPTZ,
    retract_reason TEXT
);
CREATE INDEX IF NOT EXISTS entity_aliases_active_idx ON entity_aliases (alias_norm)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS entity_aliases_entity_idx ON entity_aliases (entity_id);
CREATE INDEX IF NOT EXISTS entity_aliases_source_idx ON entity_aliases (source_event_id);

-- A claim's content never changes; only its status moves, and only towards
-- 'retracted'. A new belief is a new claim.
CREATE OR REPLACE FUNCTION entity_aliases_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.entity_id IS DISTINCT FROM OLD.entity_id
       OR NEW.alias IS DISTINCT FROM OLD.alias
       OR NEW.alias_norm IS DISTINCT FROM OLD.alias_norm
       OR NEW.alias_kind IS DISTINCT FROM OLD.alias_kind
       OR NEW.role_of_owner IS DISTINCT FROM OLD.role_of_owner
       OR NEW.excerpt IS DISTINCT FROM OLD.excerpt
       OR NEW.source_event_id IS DISTINCT FROM OLD.source_event_id
       OR NEW.confidence IS DISTINCT FROM OLD.confidence
       OR NEW.admission IS DISTINCT FROM OLD.admission
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'entity_aliases: a claim is never edited, retract it and add a new one';
    END IF;
    IF OLD.status = 'retracted' OR NEW.status NOT IN (OLD.status, 'retracted') THEN
        RAISE EXCEPTION 'entity_aliases: status % -> % is forbidden', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS entity_aliases_claims ON entity_aliases;
CREATE TRIGGER entity_aliases_claims
    BEFORE UPDATE ON entity_aliases
    FOR EACH ROW EXECUTE FUNCTION entity_aliases_guard();

-- Which identity claims an edge was attached through: what a retraction
-- must report. Empty for edges attached by name.
ALTER TABLE relations ADD COLUMN IF NOT EXISTS via_alias_ids BIGINT[] NOT NULL DEFAULT '{}';
