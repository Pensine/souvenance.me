-- Dimension des embeddings alignée sur le backend par défaut (nomic, 768-d).
-- BGE-M3 (1024-d) reste possible : voir PENSINE_EMBEDDING_BACKEND.
--
-- Les mémoires sont des projections recalculables : changer de modèle ne
-- détruit rien d'irremplaçable, il suffit de relancer la consolidation pour
-- réembedder. Les events, eux, ne bougent jamais.
ALTER TABLE memories ALTER COLUMN embedding TYPE VECTOR(768) USING NULL;
