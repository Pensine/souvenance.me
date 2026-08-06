# Pensine — Installation complète (le kit)

*Cette doc est écrite pour être suivie par un humain **ou par une IA** : collez
ce repo dans Claude Code sur votre VPS et dites « installe la Pensine en
suivant docs/kit-installation.md ». Chaque étape a sa commande de vérification.*

## Ce que vous obtenez

Une mémoire vivante auto-hébergée, interrogée via Claude : vos conversations,
votre log de bord quotidien et vos dépôts (vocaux, photos, PDF) deviennent une
mémoire consolidée chaque nuit, que vous interrogez depuis claude.ai
(« qu'est-ce que je pensais de X l'an dernier ? »). Tout vous appartient :
PostgreSQL chez vous, fichiers originaux conservés à vie, export SQL/markdown
permanent. Aucun lock-in : l'intelligence est un adaptateur — CLI Claude,
clé API, ou n'importe quel modèle local via Ollama (Mistral, Qwen, Llama…) —
changeable à tout moment. Self-hosted intégral possible.

## Prérequis

| Quoi | Pourquoi | Vérifier |
|---|---|---|
| VPS Linux (Debian/Ubuntu) — dimensionné selon vos briques (voir « Ordres de grandeur ») | héberge tout | `free -h` |
| Docker + compose v2 | PostgreSQL+pgvector | `docker compose version` |
| Python ≥ 3.11 | serveur MCP, API, crons | `python3 --version` |
| Un domaine pointé sur le VPS | HTTPS (claude.ai exige un MCP distant) | `dig +short votre.domaine` |
| Un backend d'IA au choix : CLI Claude, clé API, ou Ollama (modèles open source) | l'intelligence (adaptateur) | `claude --version`, une clé, ou `ollama list` |
| ffmpeg (**requis** avec `--with-local`) | décodage audio (WhisperX) + vidéos | `ffmpeg -version` |

### Ordres de grandeur (RAM constatée — à adapter à votre configuration)

| Brique | RAM résidente | Optionnelle ? |
|---|---|---|
| Cœur (API, MCP, Postgres) | ~1 Go | non |
| Embeddings `nomic` (défaut) | ~0,5 Go | oui (`PENSINE_EMBEDDINGS=0` → plein-texte) |
| Embeddings `bge-m3` | ~2 Go | oui (alternative à nomic) |
| WhisperX large-v3 (transcription) | ~3 Go pendant les cycles nocturnes | oui (`--with-local`) |
| Pillow, Docling | négligeable | oui (`--with-local`) |

Chaque brique dégrade proprement si elle manque : rien n'est jamais perdu,
le traitement rattrape quand la brique arrive. Composez selon votre budget.

## Installation

```bash
git clone <votre-fork-ou-le-repo> /opt/pensine && cd /opt/pensine
./install.sh --with-local     # sans --with-local : pas de transcription locale
                              # (les dépôts audio attendent, rien n'est perdu)
```

**VPS déjà occupé par un autre Postgres ?** Le port hôte est configurable :
`PENSINE_DB_PORT=5433 ./install.sh` (ou éditez `PENSINE_DB_PORT` **et** le port
dans `PENSINE_DATABASE_URL` de `.env`, puis `docker compose up -d db`).
La base Pensine reste isolée dans son conteneur ; seul le port d'écoute
sur 127.0.0.1 change.

Le script : génère `.env` avec des secrets aléatoires, lance la base, applique
le schéma, installe le venv, exécute les tests, installe et démarre les
services systemd (`pensine-api` :8300, `pensine-mcp` :8400), affiche le cron
à ajouter.

Puis **éditez `.env`** :
- `PENSINE_OWNER_NAME=` votre prénom (utilisé par les prompts de consolidation)
- `PENSINE_PUBLIC_BASE_URL=https://votre.domaine`
- `PENSINE_CALENDAR_ICS_URLS=` l'URL ICS privée de votre agenda (optionnel —
  Google Agenda : Paramètres → votre agenda → « Adresse secrète au format iCal »)
- autre backend : `PENSINE_LLM_BACKEND=api` ou `ollama` — ex. api :
  `PENSINE_ANTHROPIC_API_KEY=sk-ant-…`

Redémarrez après édition : `sudo systemctl restart pensine-api pensine-mcp`

### Reverse proxy (HTTPS)

```bash
sudo apt install -y caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
# éditez le domaine, décommentez basicauth pour /mcp, puis :
sudo systemctl reload caddy
```

⚠️ **N'exposez pas `/mcp` sans protection** : c'est votre mémoire intime.
Deux options selon votre compte claude.ai : **basicauth** si la section
« Request headers » apparaît dans votre boîte d'ajout de connecteur (valeur :
`Basic <base64 de user:motdepasse>`), sinon un **chemin secret** (`handle
/mcp-<48 caractères hex>* { rewrite * /mcp ... }` — l'URL est le secret,
claude.ai n'a alors rien à configurer). Sans l'un des deux, un `401` déclenche
côté claude.ai un flux OAuth voué à l'échec.

**Si votre reverse proxy tourne en conteneur Docker** (au lieu du Caddy
systemd ci-dessus) : il ne peut pas joindre `127.0.0.1` de l'hôte. Mettez
`PENSINE_BIND_HOST=<passerelle du bridge>` (ex. `172.18.0.1`) dans `.env`,
faites pointer le vhost dessus, et ouvrez le couloir dans le pare-feu :
`ufw allow from <sous-réseau docker> to <passerelle> port 8300,8400 proto tcp`.
Attention aussi au bind mount du Caddyfile : éditez-le **en place** (`cat >`,
éditeur) — un `sed -i` recrée le fichier et détache silencieusement le mount.

### Cron de consolidation

`crontab -e`, puis collez ce qu'`install.sh` a affiché (nocturne 03:00 + REM
dimanche 04:00 + `scripts/backup.sh` quotidien recommandé).

### Vérifications finales

```bash
# API de dépôt (403/401 attendu sans token = OK)
curl -s -o /dev/null -w '%{http_code}\n' https://votre.domaine/deposit -X POST   # 401
# Dépôt réel
source .env && curl -s https://votre.domaine/deposit \
  -H "Authorization: Bearer $PENSINE_DEPOSIT_TOKEN" \
  -F "file=@/etc/hostname" -F "note=test"                                        # {"ok":true,...}
# Consolidation à blanc
./.venv/bin/python consolidation/nightly.py
```

## Connexion à claude.ai

1. claude.ai → **Paramètres → Connecteurs → Ajouter un connecteur personnalisé**
   → URL : `https://votre.domaine/mcp` (avec les identifiants basicauth si configurés).
2. Créez un **projet Claude « Pensine »** et activez-y le connecteur. C'est là
   que vivent vos conversations, votre log de bord, votre interview fondatrice.
3. Testez : « Utilise recall pour chercher "test" dans ma mémoire. »

## Le raccourci iOS « Pensine » (dépôt en deux taps)

App Raccourcis → **+** → nommez « Pensine » :
1. Action **Recevoir** : « Recevoir Toute entrée depuis la feuille de partage »
   (types : images, fichiers, contenus multimédias)
2. Action **Obtenir le contenu de l'URL** :
   - URL : `https://votre.domaine/deposit` — Méthode : **POST**
   - En-têtes : `Authorization` = `Bearer VOTRE_PENSINE_DEPOSIT_TOKEN` (dans `.env`)
   - Corps : **Formulaire** → champ `file` = *Entrée du raccourci* (type Fichier)
3. Réglages du raccourci → activez « Afficher dans la feuille de partage »

Usage : vocal WhatsApp → appui long → Transférer → Partager → **Pensine**.
Photo, PDF, mémo vocal : pareil. Deux taps, c'est dans la mémoire.

## Démarrer (l'ordre qui marche)

1. **Interview fondatrice** (docs/interview-fondatrice.md) : 3-4 sessions dans
   le projet Claude, transcripts ingérés via `scripts/ingest_interview.py` —
   c'est elle qui amorce le corpus. Sans elle, `recall` est vide.
2. **Log de bord quotidien** : 2-3 min à la voix dans le projet Claude
   (« daily_log : … ») — 4 champs : fait du jour, décision/hésitation, état, cap.
3. **Personnalisez `constitution.yaml`** : motifs à exclure (ex. votre sphère
   professionnelle), puis commitez — la constitution se révise par Git.
4. Les dépôts Pensine, à l'envie. La mémoire se construit en silence.

## Fonctions avancées (phase 2)

**Web app timeline** — `https://votre.domaine/app` : la replongée visuelle.
Timeline de tous les dépôts (audio écoutable en place, photos) et mémoires,
filtrable par texte/type/année. Mot de passe : `PENSINE_WEBAPP_PASSWORD`
(généré par `install.sh`).

**Graphe temporel** — la consolidation extrait entités et relations avec leurs
périodes de validité ; un fait qui en remplace un autre (« habite à ») ferme
l'ancienne arête sans jamais l'effacer. `recall` renvoie une section `graphe` ;
« qu'est-ce qui était vrai en 2024 ? » est une requête, pas une reconstruction.

**Miroir** — dans Claude : « utilise mirror avec ma question ». Trajectoire par
trimestre, entités dominantes, contradictions ouvertes — le système rapporte,
ne juge pas, et rend la main (« qu'en dis-tu ? »).

**Choisir son moteur d'embeddings** — `nomic` par défaut (768-d, ~500 Mo :
tient sur 4 Go de RAM) ; `bge-m3` (1024-d, ~2 Go résidents : meilleur
en français). Pour changer :
```bash
# dans .env : PENSINE_EMBEDDING_BACKEND=bge-m3   (ou nomic)
./.venv/bin/python scripts/reembed.py     # redimensionne et recalcule tout
sudo systemctl restart pensine-api pensine-mcp
```
Les mémoires sont des projections recalculables : l'opération est sans risque
et réversible.

**Empreintes vocales** (nécessite `--with-local`) — l'enrôlement est un acte
explicite :
```bash
./.venv/bin/python scripts/enroll_speaker.py --name "Prénom" échantillon.wav
```
Les cycles suivants identifient cette voix dans les dépôts. L'expéditeur d'un
vocal transféré (métadonnée du canal) prime toujours sur le ML.

**Persona** — chaque mois, le compilateur produit une proposition d'identité
narrative dans `persona/propositions/` (chapitres, thèmes, tensions, chaque
affirmation sourcée et pesée). Elle n'entre en vigueur que ratifiée par vous :
```bash
./.venv/bin/python scripts/ratify_persona.py 2026-XX-XX-persona.md
```

**Tests de fidélité** — mesurez ce que le jumeau sait vraiment (seuil phase 2 :
9/10 factuel) :
```bash
./.venv/bin/python scripts/fidelity_test.py generate --n 10
./.venv/bin/python scripts/fidelity_test.py run
./.venv/bin/python scripts/fidelity_test.py report   # score par domaine
```

## Reprendre son historique et aller plus loin

**Importer vos années ChatGPT / Claude** — demandez vos exports officiels
(Paramètres → Données), puis :
```bash
./.venv/bin/python scripts/import_history.py ~/export/conversations.json
```
Dès la première nuit, `recall` connaît des années de vous. Relançable sans
risque (déduplication), filtré par votre constitution.

**Le log de bord en un geste** — raccourci iOS « Log », quatre actions :
1. **Dicter le texte** (Arrêter l'écoute : *Après une pause*)
2. **Demander une entrée** (type Texte, **Réponse par défaut** = *Texte
   dicté*, plusieurs lignes autorisées) — la dictée s'affiche pré-remplie et
   éditable : vous corrigez les mots mal entendus avant l'envoi
3. **Obtenir le contenu de l'URL** : `POST https://votre.domaine/log`,
   en-tête `Authorization: Bearer <PENSINE_DEPOSIT_TOKEN>`, corps
   **Formulaire** → champ texte `text` = *Entrée fournie*
4. (optionnel) Ajouter à l'écran d'accueil — le geste du soir

⚠️ Piège classique des deux raccourcis : le **Corps de la requête** doit être
**Formulaire** (pas JSON, pas Fichier), sinon l'API répond 422 « Field
required ». Et l'ordre des actions compte : on dicte *avant* d'envoyer.

**L'interview fondatrice, conduite par le système** — dans Claude :
« lance interview session 1 » ; le système pose les questions et s'ingère
lui-même à la fin (`interview_save`).

**Jalons du moteur temporel** — dans Claude : « ajoute le jalon UTMB 2027 au
27 août » (outil `landmark`). Courses, déménagements, chapitres : ils
deviennent les coordonnées humaines du cadre temporel (« avant ou après
l'UTMB ? »).

**Capsules temporelles** — « scelle une capsule pour le 15 juin 2027 : … ».
Elle refera surface dans vos conversations ce jour-là — jamais en
notification.

**Le Livre de l'année** — `scripts/yearbook.py --year 2026` : votre année
écrite depuis la mémoire, en markdown + HTML imprimable.

**Compute 100 % local** — `PENSINE_LLM_BACKEND=ollama` (+
`PENSINE_OLLAMA_MODEL`) : la consolidation tourne sans aucun service
externe. La vision passe en pause, tout le reste fonctionne.

**Sauvegarde hors site chiffrée** — définissez `RESTIC_REPOSITORY` et
`RESTIC_PASSWORD` dans `.env` : `backup.sh` pousse automatiquement vers
B2/S3/SFTP avec rotation 14 j / 12 sem / 30 ans.

## Sauvegarde, export, réversibilité

- `scripts/backup.sh` : dump SQL + rsync des médias — **formats éternels**,
  lisibles dans 30 ans sans le kit. Copiez le dossier hors VPS (restic/rclone).
- Export total à tout moment : le dump SQL **est** l'export (events = source
  de vérité), les médias sont des fichiers ordinaires, le persona est du
  markdown dans Git.
- Tout arrêter : `docker compose down` + désactiver les services. Vos données
  restent dans le volume Postgres et `PENSINE_MEDIA_ROOT`.

## Dépannage

| Symptôme | Cause probable | Remède |
|---|---|---|
| `recall` vide | corpus jeune, consolidation pas passée | ingérez l'interview, lancez `consolidation/nightly.py` à la main |
| `nightly_paused` dans l'audit | `claude` CLI absent, non connecté, **ou jeton révoqué** (une reconnexion ailleurs peut le faire tourner) | `claude /login` sur le VPS — attention : l'URL OAuth se replie sur plusieurs lignes dans le terminal, copiez-la en entier (le scope `org:create_api_key` doit être complet) |
| médias `media_skip` dans l'audit | WhisperX/Pillow/Docling absents | `./.venv/bin/pip install -e ".[local]"` — repris au cycle suivant |
| 503 sur /deposit | token non configuré | `PENSINE_DEPOSIT_TOKEN` dans `.env`, restart |
| `install.sh` : « port déjà occupé » | un autre Postgres écoute sur 5432 | `PENSINE_DB_PORT=5433 ./install.sh` |
| claude.ai ne voit pas le connecteur | /mcp pas accessible en HTTPS | testez `curl https://votre.domaine/mcp` ; vérifiez Caddy |

Le journal d'audit (`SELECT * FROM audit_log ORDER BY at DESC LIMIT 50;`)
raconte tout ce que le système a fait — c'est la couche 7, elle est là pour ça.
