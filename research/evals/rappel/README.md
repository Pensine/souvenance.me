# Banc de rappel — la Pensine retrouve-t-elle la preuve ?

Une mémoire qui n'invente rien mais ne retrouve rien ne sert à rien. Ce banc
mesure **le rappel seul** : quand on pose une question, les souvenirs qui
portent la réponse sont-ils parmi les premiers que `recall` remonte ?

Aucun juge LLM, aucune API, aucune consolidation : tout est local et
déterministe. Une commande :

```bash
research/evals/rappel/run.sh            # tout (~2 h 30 sur un Mac M-series 16 Go, dont ~2 h 15 de bge-m3)
research/evals/rappel/run.sh --rapide   # sans les rerankers (~4 min)
```

## Protocole

- **Données** : LoCoMo-10 (Maharana et al., ACL 2024), 10 conversations,
  5 882 tours de dialogue datés. Chaque question porte ses preuves
  (`evidence`, ex. `D1:3` = session 1, tour 3).
- **Corpus** : un tour = une mémoire (`« Locuteur : texte [photo : légende] »`),
  datée de sa session, embedding nomic-embed-text-v1.5 (le défaut de la
  Pensine). Base jetable `rappel_c<n>` sur le conteneur `locomo-eval`
  (port 5442), schéma + migrations du dépôt. Jamais la prod.
- **Pourquoi les tours bruts et pas les mémoires consolidées** : la
  consolidation coûte un appel LLM par lot de sessions et mesurerait deux
  choses à la fois (ce que le modèle retient, puis ce que la recherche
  retrouve). Les tours bruts isolent la recherche, et les preuves LoCoMo
  pointent exactement sur eux : on sait sans juge si la bonne pièce est
  remontée. La consolidation reste mesurable à part (`../locomo/`).
- **Chemin mesuré** : la première étape de `recall`, à l'identique —
  24 candidats (`db.search_memories`), puis `temporal.rank` (orientation de
  la question, période visée). Horloge gelée au lendemain de la dernière
  session. Aucune écriture pendant la mesure (`mark=False`, rollback).
- **Métriques** (catégories 1 à 4, 1 535 questions ; la catégorie 5,
  adversariale, est à part dans `results/resume*.json`) : Recall@5 et
  Recall@10 = part des tours-preuves présents dans les 5 / 10 premiers ;
  MRR@10 = inverse du rang du premier tour-preuve (0 s'il n'est pas dans les
  10). Intervalles de confiance à 95 % par **bootstrap apparié** sur les
  questions (`rapport.py`, graine fixe).
- **Réglage honnête** : les trois réglages du plein-texte (racine par
  préfixe, seuil de score 0,6, poids égaux) ont été choisis sur la
  **conversation 1 seulement** (grille de 24 combinaisons). Les
  conversations 2 à 10 n'ont jamais servi au réglage : c'est le chiffre qui
  compte.

## Conditions

| condition | ce que c'est |
|---|---|
| avant | le code d'avant : vecteur seul, puis `temporal.rank` |
| plein-texte | diagnostic : la liste plein-texte seule (après seuil) |
| hybride | vecteur + plein-texte fusionnés (RRF, k=60) |
| hybride+temps | + période visée par la question (`temporal.cues`) |
| rerank-minilm | + `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` sur les 30 premiers |
| rerank-bge-m3 | + `BAAI/bge-reranker-v2-m3` sur les 30 premiers |

## Résultats (28 octobre 2026)

Conversations 2 à 10, jamais vues au réglage — 1 385 questions. Entre
crochets : IC 95 % de l'écart à « avant ».

| condition | R@5 | R@10 | MRR@10 | latence de recherche |
|---|---|---|---|---|
| avant | 0,578 | 0,674 | 0,504 | 7 ms |
| hybride | 0,616 [+0,025 ; +0,050] | 0,698 [+0,013 ; +0,035] | 0,527 [+0,009 ; +0,037] | 8 ms |
| hybride+temps | 0,639 [+0,045 ; +0,077] | 0,723 [+0,035 ; +0,062] | 0,547 [+0,028 ; +0,059] | 9 ms |
| rerank-minilm | 0,672 [+0,074 ; +0,115] | 0,734 [+0,042 ; +0,078] | 0,618 [+0,095 ; +0,133] | ~200 ms |
| rerank-bge-m3 | **0,751** [+0,152 ; +0,193] | **0,799** [+0,107 ; +0,141] | **0,692** [+0,168 ; +0,210] | 1,5 à 4 s |

Toutes les tranches (conv. 1, catégories, questions avec repère temporel) :
[`results/tableau.md`](results/tableau.md).

Ce qu'on en retient :

1. **L'hybride naïf faisait moins bien que le vecteur seul** (R@5 0,546
   contre 0,618 sur la conv. 1). Cause : un prénom présent dans un tour sur
   deux suffisait à faire entrer un tour quelconque dans la liste plein-texte,
   et la fusion par rang le traitait en candidat sérieux. Le seuil de score
   (garder ce qui partage avec la question au moins 60 % du poids IDF de ses
   mots) a renversé le résultat. Résultat négatif gardé ici : il dit pourquoi
   le seuil existe.
2. **La période visée ne change rien aux questions sans repère** (écart
   exactement nul sur 1 323 questions) et fait gagner **+17 points de R@5**
   sur les 212 qui en ont un (« in June », « in 2023 », « 4 years ago »).
3. **Le reranker est le plus gros levier**, et bge-reranker-v2-m3 double
   presque le gain de MiniLM — au prix de 10 à 20 fois plus de temps.
4. Les questions multi-sauts (cat. 1) restent dures : R@10 0,58 au mieux.
   Chercher une seule fois avec la question entière ne suffit pas quand la
   réponse est répartie sur plusieurs souvenirs.

## RAM et latence des rerankers (Mac M-series, 16 Go, CPU seul)

Mesuré dans un processus neuf (`mesure_reranker.py`, 30 paires par
question, 20 questions ; `results/reranker_ram_latence.jsonl`) :

| modèle | disque | RAM après inférence | latence (30 paires) |
|---|---|---|---|
| mmarco-mMiniLMv2-L12-H384 | 0,5 Go | +0,64 Go | 161 ms (p95 178) |
| bge-reranker-v2-m3 | 2,1 Go | +1,6 Go | 1,5 s (p95 1,7) ; ~3,9 s en moyenne dans le banc, tours longs et embedding chargé à côté |

Le processus du banc complet (nomic + bge-m3 chargés) culmine à 2,5 Go.
Ordres de grandeur par brique, pas un prérequis : chacun choisit selon sa
machine (`PENSINE_RERANKER`, vide par défaut).

## Limites

- Tours bruts, pas mémoires consolidées : en production, une mémoire
  résume souvent plusieurs tours, et le texte est plus dense. Le classement
  des conditions devrait tenir ; les chiffres absolus, non.
- Corpus en anglais seulement. La configuration plein-texte (`simple` +
  unaccent) et les deux rerankers sont multilingues, mais le gain en
  français n'est pas mesuré ici.
- Une conversation LoCoMo = 400 à 700 souvenirs ; une vraie vie en compte
  vite des milliers. Le rappel baisse avec la taille du corpus, la latence
  du plein-texte (index GIN) et du vecteur aussi, celle du reranker non
  (toujours 30 candidats).
- Latence du reranker mesurée sur CPU. `PENSINE_RERANK_DEVICE=mps` (Apple)
  ou `cuda` l'accélèrent, non mesuré ici.
- Les repères temporels relatifs (« 4 years ago ») sont calculés depuis le
  lendemain de la dernière session : ce sont des dates du corpus, pas
  d'aujourd'hui, comme dans la vraie Pensine où le cadre est la date du jour.
