-- « Vu, rien à en tirer » : un examen sans récolte doit rester une conclusion.
--
-- Un événement était réputé « à consolider » tant qu'aucune mémoire ne le
-- citait. Conséquence : un événement dont la consolidation décide légitimement
-- qu'il n'y a rien à retenir — un log de bord vide, un test, une notification
-- sans contenu — n'était jamais marqué comme traité. Il revenait chaque nuit,
-- coûtait un appel au modèle, et s'accumulait avec ses semblables dans le
-- prompt de tous les cycles suivants.
--
-- Le marqueur ne peut pas vivre sur `events` : le trigger append-only interdit
-- tout UPDATE, et c'est bien ainsi. Le fait qu'un cycle ait examiné un
-- événement n'est pas un fait sur la vie de la personne — c'est un état du
-- traitement, donc une projection, donc sa place est ici.
--
-- REJEU COMPLET : `DELETE FROM consolidation_marks;` puis relancer la
-- consolidation fait relire tout le log au moteur courant. C'est la promesse
-- centrale de l'architecture — un meilleur modèle relit la même vie — et elle
-- reste vraie parce que ce marqueur est jetable.
CREATE TABLE consolidation_marks (
    event_id BIGINT PRIMARY KEY REFERENCES events(id),
    examined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    produced_memory BOOLEAN NOT NULL DEFAULT false
);

-- Les événements déjà consolidés avant cette migration n'ont pas de marqueur.
-- On les marque d'après ce qu'ils ont produit, sinon le premier cycle
-- réexaminerait tout le corpus et créerait des mémoires en double.
INSERT INTO consolidation_marks (event_id, examined_at, produced_memory)
SELECT DISTINCT e.id, now(), true
FROM events e
WHERE EXISTS (SELECT 1 FROM memories m WHERE e.id = ANY(m.source_event_ids))
ON CONFLICT (event_id) DO NOTHING;
