# Interview fondatrice — 3-4 sessions (phase 0)

Audio de préférence (trajet, marche). Chaque session : 30-45 min, dans le
projet Claude « Pensine ». Le transcript de chaque session est ingéré comme
premiers events (`scripts/ingest_interview.py`). Ensuite l'interview se
dissout dans l'usage : le système comble ses trous en glissant une question
dans les conversations naturelles, jamais en interrogatoire.

Consigne à donner à Claude en début de session : *« Tu conduis ma session
d'interview fondatrice n°X (thème ci-dessous). Une question à la fois,
relance sur le concret et les exemples vécus, ne juge jamais, ne synthétise
qu'à la fin. »*

## Session 1 — Biographie et chapitres
- Les chapitres de ta vie, comme tu les découperais toi (titres, tournants).
- Les 3-4 événements qui t'ont le plus façonné — et ce qu'ils ont changé.
- Les lieux qui comptent (et pourquoi eux).
- Ce que tu gardes de ton enfance ; ce que tu as choisi de laisser.

## Session 2 — Valeurs, spiritualité, contradictions
- Ce que tu ne négocies pas. Ce que tu as déjà trahi, et ce que ça t'a appris.
- La place du spirituel ou du sens, si elle existe pour toi : pratiques,
  doutes, ce que « faire fructifier ce qui t'a été confié » veut dire
  concrètement.
- Deux tensions assumées (ex. ambition ↔ discrétion, ailleurs ↔ maison) —
  les nommer sans les résoudre.
- Ce qui te met en colère de façon fiable. Ce qui te répare.

## Session 3 — Style de décision et travail
- Trois décisions importantes récentes : comment elles se sont vraiment
  prises (pas la version propre — la vraie séquence).
- Ce que tu fais quand tu hésites. Ton rapport au risque, à l'argent,
  au temps.
- Comment tu travailles bien : conditions, heures, formats. Ce qui te vide.
- Ton style d'écriture : trois textes de toi que tu trouves justes.

## Session 4 — Relations, projets, peurs, horizon
- Les personnes qui comptent : ce que chaque relation te donne et te demande.
  *(Règle des tiers : on parle de ta relation à eux, pas de leurs confidences.)*
- Les projets en cours et rêvés — et lesquels sont des vrais.
- Les peurs opérantes (celles qui influencent des décisions).
- Dans 10 ans : qu'est-ce que ce système devrait pouvoir te rappeler
  d'aujourd'hui ?

## Ingestion

```bash
./.venv/bin/python scripts/ingest_interview.py --session 1 --date 2026-08-10 transcript_s1.txt
```
