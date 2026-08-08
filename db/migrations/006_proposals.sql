-- Mémoire proposée : l'IA repère, l'utilisateur tranche.
--
-- Une conversation contient plus de choses mémorables qu'on ne prend la peine
-- d'en dicter. Laisser l'assistant les repérer supprime la friction de capture
-- — la première cause d'abandon documentée de ce genre de système.
--
-- Mais une mémoire écrite unilatéralement par une IA est exactement ce que ce
-- projet reproche aux assistants du marché. La différence n'a jamais été de
-- savoir qui repère : elle est de savoir qui décide, et si l'on peut voir ce
-- qui a été décidé. D'où cette table : une proposition n'est PAS un événement.
-- Elle attend. Rien n'entre dans le substrat sans un second acte.
--
-- Les refus sont conservés au même titre que les acceptations : ce qu'on ne
-- veut pas voir mémorisé est une information sur soi, et un journal qui
-- n'garderait que les oui ne dirait pas la vérité sur ce qui s'est joué.
CREATE TABLE memory_proposals (
    id BIGSERIAL PRIMARY KEY,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content TEXT NOT NULL,          -- ce que l'assistant a compris, en clair
    kind TEXT NOT NULL,             -- 'fact' (vérifiable) | 'inference' (sur la personne)
    rationale TEXT,                 -- pourquoi il pense que ça compte, montré à l'utilisateur
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'confirmed' | 'declined'
    decided_at TIMESTAMPTZ,
    decline_reason TEXT,
    event_id BIGINT REFERENCES events(id),    -- rempli à la confirmation seulement
    CONSTRAINT memory_proposals_kind CHECK (kind IN ('fact', 'inference')),
    CONSTRAINT memory_proposals_status CHECK (status IN ('pending', 'confirmed', 'declined')),
    -- un événement n'existe que pour une proposition confirmée, et réciproquement
    CONSTRAINT memory_proposals_event_iff_confirmed
        CHECK ((status = 'confirmed') = (event_id IS NOT NULL))
);
CREATE INDEX memory_proposals_pending_idx ON memory_proposals(proposed_at)
    WHERE status = 'pending';

-- Provenance des événements : distinguer ce que l'utilisateur a délibérément
-- déposé de ce qu'un assistant a proposé et qu'il a accepté.
--
-- Sans cette colonne, les deux deviennent indiscernables dès le lendemain, et
-- la question « qu'est-ce que le système a décidé de retenir de lui-même ? »
-- n'a plus de réponse. C'est précisément la question qu'on ne peut pas poser
-- aux assistants du marché ; ici elle doit rester une simple requête.
ALTER TABLE events ADD COLUMN origin TEXT NOT NULL DEFAULT 'declared';
ALTER TABLE events ADD CONSTRAINT events_origin
    CHECK (origin IN ('declared', 'proposed'));
CREATE INDEX events_origin_idx ON events(origin);
