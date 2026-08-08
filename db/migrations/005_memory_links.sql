-- Liaisons entre souvenirs — le rappel devient un réseau, plus un index.
--
-- Jusqu'ici une mémoire pointait vers ses events sources (provenance) et vers
-- son successeur (reconsolidation). Rien ne reliait deux souvenirs entre eux :
-- le graphe relie des *entités*, pas des *souvenirs*. Conséquence, le rappel
-- était une recherche par similarité — un index plat. Une mémoire humaine
-- récupère de proche en proche : un souvenir en active un autre, qui ne partage
-- pas forcément son vocabulaire.
--
-- Deux origines de lien :
--   'shared_event' — structurel, posé à la consolidation : deux mémoires nées
--                    du même événement appartiennent au même épisode.
--   'co_recall'    — appris, hebbien : deux mémoires qui remontent ensemble
--                    voient leur lien se renforcer. Ce qui s'active ensemble
--                    se lie.
--
-- Arête non orientée, stockée une seule fois (source_id < target_id) : une
-- association n'a pas de sens de lecture. `kind` garde l'origine de la
-- création ; la force, elle, s'accumule quelle que soit la voie.
CREATE TABLE memory_links (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES memories(id),
    target_id BIGINT NOT NULL REFERENCES memories(id),
    kind TEXT NOT NULL,                 -- 'shared_event' | 'co_recall'
    strength REAL NOT NULL DEFAULT 0.1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_reinforced_at TIMESTAMPTZ,
    CONSTRAINT memory_links_canonical CHECK (source_id < target_id),
    CONSTRAINT memory_links_strength_range CHECK (strength > 0.0 AND strength <= 1.0),
    CONSTRAINT memory_links_unique UNIQUE (source_id, target_id)
);

CREATE INDEX memory_links_source_idx ON memory_links(source_id, strength DESC);
CREATE INDEX memory_links_target_idx ON memory_links(target_id, strength DESC);

-- Note sur l'oubli : contrairement aux mémoires, un lien trop faible est
-- SUPPRIMÉ, pas conservé au plancher. Les liens sont une projection —
-- recalculables depuis les events — et les garder tous ferait croître la table
-- en O(n²). Le substrat, lui, n'est jamais touché.
