-- Embedding dimension aligned with the default backend (nomic, 768-d).
-- BGE-M3 (1024-d) remains possible: see PENSINE_EMBEDDING_BACKEND.
--
-- Memories are recomputable projections: changing the model destroys nothing
-- irreplaceable, rerunning consolidation is enough to re-embed. Events, for
-- their part, never change.
ALTER TABLE memories ALTER COLUMN embedding TYPE VECTOR(768) USING NULL;
