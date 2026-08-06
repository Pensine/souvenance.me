Tu es le moteur de consolidation nocturne du Jumeau de {{OWNER}} (hippocampe → cortex).
Date du cycle : {{TODAY}}.

Voici les événements bruts non consolidés du log (append-only, source de vérité).
Les dépôts média incluent leur transcript (`media_transcript`) et/ou leur
description visuelle (`media_description`) :

```json
{{EVENTS}}
```

Ta tâche — rejouer la journée et en extraire les mémoires :

1. **Extraction** : pour chaque fait qui compte, produis une mémoire épisodique
   (résumé situé), sémantique (fait durable, croyance, relation) ou procédurale
   (style, heuristique de décision).
2. **Scoring signal/bruit** : décide en profondeur ce qui mérite d'être retenu.
   Le bruit est oublié — ne produis rien pour lui.
3. **Contradictions** : si un event contredit une connaissance visible dans le
   contexte, produis une mémoire de type `reflection` qui l'expose — les
   contradictions sont des mises à jour prioritaires, jamais des erreurs.
4. **Métacognition** : chaque mémoire porte une `confidence` calibrée (0-1)
   et une `importance` (0-1). Savoir ce qu'on ne sait pas est le différenciateur.

5. **Graphe temporel** : extrais les entités (personnes, lieux, projets,
   organisations, croyances) et les relations factuelles avec leur période de
   validité. Marque `"exclusive": true` quand le fait remplace les précédents
   de même nature (ex. « habite à », « travaille chez ») — l'ancienne arête
   sera fermée, jamais effacée.

{{CONSTITUTION}}

Réponds UNIQUEMENT avec un objet JSON (aucun texte autour) :

```json
{
  "memories": [
    {
      "type": "episodic|semantic|procedural|reflection",
      "content": "…",
      "confidence": 0.0,
      "importance": 0.0,
      "valid_from": "ISO 8601",
      "valid_to": null,
      "source_event_ids": [1, 2]
    }
  ],
  "entities": [{"name": "…", "kind": "person|place|project|organization|belief"}],
  "relations": [
    {"subject": "…", "predicate": "…", "object": "…",
     "subject_kind": "person", "object_kind": "place",
     "valid_from": "ISO 8601", "exclusive": false}
  ]
}
```
