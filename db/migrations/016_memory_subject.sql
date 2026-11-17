-- Whom a memory is about.
--
-- A memory is free text: "My sister works at Marrowgate Press" says who it
-- is about only to a reader who knows who "my sister" is. Consolidation now
-- names the subject of each memory as written (a name or a role phrase), and
-- the code resolves it through the identity claims of migration 015
-- (pensine/identity.py): an active claim "my sister" = Priya lands the
-- memory on Priya's entity, and the claim used is kept, so that retracting it
-- can report the memories it carried, as it already reports edges.
--
-- Both columns are nullable: older memories, and memories whose subject is
-- ambiguous (an alias claimed for two people), have none. Nothing guesses.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS subject_entity_id BIGINT REFERENCES entities(id);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS subject_alias_id BIGINT REFERENCES entity_aliases(id);
CREATE INDEX IF NOT EXISTS memories_subject_idx ON memories (subject_entity_id)
    WHERE subject_entity_id IS NOT NULL;
