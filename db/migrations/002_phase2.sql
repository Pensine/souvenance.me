-- Phase 2 : empreintes vocales, graphe renforcé

-- Empreintes vocales (ECAPA-TDNN, 192 dims) — l'enrôlement est un acte explicite (§8)
CREATE TABLE voiceprints (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES entities(id),
    embedding VECTOR(192) NOT NULL,
    sample_note TEXT,              -- provenance de l'échantillon d'enrôlement
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Graphe : upsert propre des entités
CREATE UNIQUE INDEX entities_name_kind_idx ON entities (lower(name), kind);
CREATE INDEX relations_subject_idx ON relations (subject_id, predicate)
    WHERE valid_to IS NULL;

-- Bi-temporalité complète : quand le graphe a-t-il APPRIS le fait
-- (valid_from/valid_to = temps du monde ; created_at/invalidated_at = temps du système)
ALTER TABLE relations
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN invalidated_at TIMESTAMPTZ;
