-- Identity coverage without giving up evidence: inferred claims.
--
-- A proven claim (migration 015) needs one deposit that writes the alias and
-- the name as one designation ("my sister Priya"). Many identities are never
-- written that way: "my aunt lives in Porto" one day, "Ines works at Saltire
-- Glassworks" another, "my aunt works at Saltire Glassworks", "Ines lives in
-- Porto". A second TIER of claims holds such hypotheses, kept apart from the
-- proven ones:
--
--   tier 'inferred'  built in code (pensine/identity.py, `infer`) from at
--                    least two specific attributes that the alias and the name
--                    share, each stated in different deposits; every support
--                    is quote-checked and listed in `supports`; the confidence
--                    is computed from the number of independent supports.
--                    Used in recall only with an explicit hedge, NEVER to
--                    attach edges or memory subjects (resolution reads proven
--                    claims only);
--   status 'promoted' a later deposit writes the identity form, or the owner
--                    confirms it (the memory_proposals path of migration 006):
--                    a new proven claim is written, `promoted_to` points to it;
--   status 'refuted'  contradicting evidence (the two present together in one
--                    deposit, two different cities at the same time): closed,
--                    with the reason in `retract_reason`.
ALTER TABLE entity_aliases ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'proven'
    CHECK (tier IN ('proven', 'inferred'));
ALTER TABLE entity_aliases ADD COLUMN IF NOT EXISTS supports JSONB NOT NULL DEFAULT '[]';
ALTER TABLE entity_aliases ADD COLUMN IF NOT EXISTS proposal_id BIGINT
    REFERENCES memory_proposals(id);
ALTER TABLE entity_aliases ADD COLUMN IF NOT EXISTS promoted_to BIGINT
    REFERENCES entity_aliases(id);
ALTER TABLE entity_aliases DROP CONSTRAINT IF EXISTS entity_aliases_status_check;
ALTER TABLE entity_aliases ADD CONSTRAINT entity_aliases_status_check
    CHECK (status IN ('pending', 'active', 'retracted', 'refuted', 'promoted'));
CREATE INDEX IF NOT EXISTS entity_aliases_inferred_idx ON entity_aliases (alias_norm)
    WHERE status = 'active' AND tier = 'inferred';

-- Content still never changes; status moves only towards a closed state, and
-- only an inferred claim can be promoted.
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
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.tier IS DISTINCT FROM OLD.tier
       OR NEW.supports IS DISTINCT FROM OLD.supports
       OR NEW.proposal_id IS DISTINCT FROM OLD.proposal_id THEN
        RAISE EXCEPTION 'entity_aliases: a claim is never edited, retract it and add a new one';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND (
           OLD.status IN ('retracted', 'refuted', 'promoted')
           OR NEW.status NOT IN ('retracted', 'refuted', 'promoted')
           OR (NEW.status = 'promoted' AND (OLD.tier != 'inferred' OR NEW.promoted_to IS NULL))) THEN
        RAISE EXCEPTION 'entity_aliases: status % -> % is forbidden', OLD.status, NEW.status;
    END IF;
    IF NEW.promoted_to IS DISTINCT FROM OLD.promoted_to
       AND NOT (NEW.status = 'promoted' AND OLD.status != 'promoted')
       AND NEW.promoted_to IS NOT NULL THEN
        RAISE EXCEPTION 'entity_aliases: promoted_to is set once, by the promotion';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
