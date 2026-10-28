-- Links between memories — recall becomes a network, no longer an index.
--
-- Until now a memory pointed to its source events (provenance) and to its
-- successor (reconsolidation). Nothing linked two memories to each other:
-- the graph links *entities*, not *memories*. As a result, recall was a
-- similarity search — a flat index. A human memory retrieves step by step: one
-- memory activates another, which does not necessarily share its vocabulary.
--
-- Two origins of a link:
--   'shared_event' — structural, set at consolidation: two memories born
--                    from the same event belong to the same episode.
--   'co_recall'    — learned, Hebbian: two memories that surface together
--                    see their link strengthen. What fires together
--                    wires together.
--
-- Undirected edge, stored only once (source_id < target_id): an association
-- has no reading direction. `kind` keeps the origin of creation; strength
-- accumulates whichever way it arises.
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

-- Note on forgetting: unlike memories, a link that is too weak is
-- DELETED, not kept at the floor. Links are a projection — recomputable from
-- the events — and keeping them all would make the table grow as O(n²). The
-- substrate itself is never touched.
