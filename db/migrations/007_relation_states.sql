-- Qualité des liens : une relation a un état, pas seulement des faits.
--
-- Le graphe savait dire « travaille chez X depuis 2024 » et fermer l'arête le
-- jour où ce n'est plus vrai. Il ne savait pas dire qu'une proximité s'est
-- refroidie, ni qu'une tension est montée — or c'est précisément ce qui fait
-- qu'une relation est une relation et pas un fait administratif.
--
-- Deux axes, pour la même raison que la charge affective d'un souvenir : un
-- seul curseur « bonne/mauvaise relation » écraserait des situations qui n'ont
-- rien à voir.
--
--   closeness   0 (distant) … 1 (intime)      — l'intensité du lien
--   valence    -1 (tendu) … +1 (chaleureux)   — sa couleur
--
-- Une famille peut être proche ET tendue ; un vieil ami qu'on ne voit plus,
-- lointain ET chaleureux. Avec un axe unique, les deux se ressemblent.
--
-- L'état n'est pas une colonne mutable sur l'arête : c'est une suite d'états
-- datés. Écraser la valeur ferait disparaître l'évolution, qui est justement
-- ce qu'on cherche à capter. Le passé se ferme (valid_to), il ne s'efface pas.
CREATE TABLE relation_states (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES entities(id),
    closeness REAL,
    valence REAL,
    note TEXT,                       -- ce qui a fait bouger, en une phrase
    confidence REAL NOT NULL DEFAULT 0.5,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,            -- NULL = état courant
    source_event_ids BIGINT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT relation_states_closeness CHECK (
        closeness IS NULL OR (closeness >= 0.0 AND closeness <= 1.0)),
    CONSTRAINT relation_states_valence CHECK (
        valence IS NULL OR (valence >= -1.0 AND valence <= 1.0)),
    -- au moins un axe renseigné : un état vide n'apprend rien
    CONSTRAINT relation_states_not_empty CHECK (
        closeness IS NOT NULL OR valence IS NOT NULL)
);

-- Un seul état courant par entité.
CREATE UNIQUE INDEX relation_states_current_idx
    ON relation_states(entity_id) WHERE valid_to IS NULL;
CREATE INDEX relation_states_entity_idx ON relation_states(entity_id, valid_from DESC);
