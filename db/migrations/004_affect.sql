-- Couche affective : un souvenir porte une charge, pas seulement un poids.
--
-- `importance` répond à « est-ce que ça compte ? ». Elle ne dit rien de ce qui
-- était ressenti. Un déjeuner anodin et un enterrement peuvent partager la même
-- importance ; ils n'ont pas la même charge, et une mémoire qui ne distingue pas
-- les deux ne modélise pas une personne.
--
-- Modèle circumplexe (Russell, 1980) : deux axes orthogonaux plutôt qu'un
-- curseur « bon/mauvais ». Le chagrin et la colère sont tous deux négatifs mais
-- ne se ressemblent pas — l'un est éteint, l'autre est vif. Sans le second axe,
-- ils deviennent indiscernables.
--
--   valence   -1 (pénible) … 0 (neutre) … +1 (heureux)
--   arousal    0 (calme, éteint) … 1 (intense, activé)
--
-- NULL est un état valide et distinct de zéro : « non déterminé » n'est pas
-- « neutre ». Les mémoires écrites avant cette migration restent NULL, et rien
-- ne les invente rétroactivement — les originaux sont conservés, une future
-- reconsolidation pourra les relire.
ALTER TABLE memories ADD COLUMN valence REAL;
ALTER TABLE memories ADD COLUMN arousal REAL;

ALTER TABLE memories ADD CONSTRAINT memories_valence_range
    CHECK (valence IS NULL OR (valence >= -1.0 AND valence <= 1.0));
ALTER TABLE memories ADD CONSTRAINT memories_arousal_range
    CHECK (arousal IS NULL OR (arousal >= 0.0 AND arousal <= 1.0));

-- L'intensité module la consolidation : c'est l'un des effets les mieux établis
-- de la mémoire humaine (modulation amygdalienne). Un souvenir chargé résiste à
-- l'oubli ; un souvenir tiède s'efface. L'index sert la décroissance nocturne,
-- qui filtre sur l'arousal.
CREATE INDEX memories_arousal_idx ON memories(arousal) WHERE superseded_by IS NULL;
