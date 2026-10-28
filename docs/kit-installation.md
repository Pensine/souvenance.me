# Pensine — Full installation

*This guide is written to be followed by a human **or by an AI**: open this
repository in a coding agent on your VPS (Claude Code, for example) and say
"install the Pensine by following docs/kit-installation.md". Every step has
its own check command.*

## What you get

A self-hosted living memory, queried from your AI assistant: your conversations,
your daily logbook and your deposits (voice notes, photos, PDFs) become a
memory that is consolidated every night, and that you query from claude.ai or another
MCP client ("what did I think of X last year?"). Everything belongs to you:
PostgreSQL on your machine, original files kept for life, a permanent SQL/markdown
export. No lock-in: the intelligence is an adapter — the Claude CLI,
an API key, or any local model through Ollama (Mistral, Qwen, Llama…) —
that you can swap at any time. Fully self-hosted is possible.

## Requirements

| What | Why | Check |
|---|---|---|
| Linux VPS (Debian/Ubuntu) — sized to the components you pick (see "Orders of magnitude") | hosts everything | `free -h` |
| Docker + compose v2 | PostgreSQL+pgvector | `docker compose version` |
| Python ≥ 3.11 | MCP server, API, cron jobs | `python3 --version` |
| A public HTTPS URL (see "Without buying a domain" below) | the claude.ai connector requires a remote MCP server over HTTPS; without TLS your token would travel in clear text | `dig +short your.domain` |
| An AI backend of your choice: Claude CLI, an API key, or Ollama (open-source models) | the intelligence (adapter) | `claude --version`, a key, or `ollama list` |
| ffmpeg (**required** with `--with-local`) | audio decoding (WhisperX) + videos | `ffmpeg -version` |

### Orders of magnitude (observed RAM — adjust to your setup)

| Component | Resident RAM | Optional? |
|---|---|---|
| Core (API, MCP, Postgres) | ~1 GB | no |
| `nomic` embeddings (default) | ~0.5 GB | yes (`PENSINE_EMBEDDINGS=0` → full-text search) |
| `bge-m3` embeddings | ~2 GB | yes (alternative to nomic) |
| WhisperX large-v3 (transcription) | ~3 GB during the night cycles | yes (`--with-local`) |
| Pillow, Docling | negligible | yes (`--with-local`) |

Each component degrades gracefully when it is missing: nothing is ever lost,
and processing catches up once the component is there. Build to your budget.

## Installation

```bash
git clone <your-fork-or-the-repo> /opt/pensine && cd /opt/pensine
./install.sh --with-local     # without --with-local: no local transcription
                              # (audio deposits wait, nothing is lost)
```

### Without buying a domain

A domain at ~€10/year is still the simplest option, but it is not required — all
you need is a **stable public HTTPS URL**:

- **Free dynamic subdomain** (DuckDNS, no-ip…): `you.duckdns.org`
  pointed at your VPS. Caddy obtains the certificate as usual.
- **Tailscale Funnel**: exposes a local service behind a
  `*.ts.net` HTTPS URL, with no DNS and no open port. Handy if you do not want
  to expose anything directly.
- **A subdomain of a domain you already own** (`memory.mydomain.com`):
  zero extra cost.

Whichever option you pick, that URL goes into `PENSINE_PUBLIC_BASE_URL`,
into the reverse proxy vhost, and into both iOS shortcuts.

**VPS already running another Postgres?** The host port is configurable:
`PENSINE_DB_PORT=5433 ./install.sh` (or edit `PENSINE_DB_PORT` **and** the port
in `PENSINE_DATABASE_URL` in `.env`, then `docker compose up -d db`).
The Pensine database stays isolated in its container; only the listening port
on 127.0.0.1 changes.

The script: generates `.env` with random secrets, starts the database, applies
the schema and then the migrations (`db/migrations/`, through `scripts/migrate.py`),
sets up the venv, runs the tests, installs and starts the systemd services
(`pensine-api` :8300, `pensine-mcp` :8400), and prints the cron lines to add.

**Offline place names** (recommended, ~10 MB) — so that a deposit with a location
gets the name of its town without querying any mapping service:
```bash
sudo mkdir -p /var/lib/pensine/geo && sudo chown "$(whoami)" /var/lib/pensine/geo
scripts/install_geonames.sh          # safe to re-run: updates the data
```
(another folder: `PENSINE_GEO_DIR=` in `.env`, before running the script.)
Without this copy, coordinates are kept and the place simply has no name.

Then **edit `.env`**:
- `PENSINE_OWNER_NAME=` your first name (used by the consolidation prompts)
- `PENSINE_PUBLIC_BASE_URL=https://your.domain`
- `PENSINE_CALENDAR_ICS_URLS=` the private ICS URL of your calendar (optional —
  Google Calendar: Settings → your calendar → "Secret address in iCal format")
- another backend: `PENSINE_LLM_BACKEND=api` or `ollama` — e.g. api:
  `PENSINE_ANTHROPIC_API_KEY=sk-ant-…` (the api backend also needs
  `./.venv/bin/pip install -e ".[api]"`)
- optional: `PENSINE_VERIFY=code` so that evidence checking
  (each memory cites the passage it rests on) sticks to the free
  checks instead of having the model review doubtful ones;
  `PENSINE_TRANSCRIBE_LANGUAGE=fr` to force the language of voice notes (empty =
  automatic detection, recommended if you speak several languages)

Restart after editing: `sudo systemctl restart pensine-api pensine-mcp`

### Reverse proxy (HTTPS)

```bash
sudo apt install -y caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
# edit the domain, uncomment basicauth for /mcp, then:
sudo systemctl reload caddy
```

⚠️ **Do not expose `/mcp` without protection**: it is your intimate memory.
Two options depending on your claude.ai account: **basicauth** if the
"Request headers" section appears in your add-connector dialog (value:
`Basic <base64 of user:password>`), otherwise a **secret path** (`handle
/mcp-<48 hex characters>* { rewrite * /mcp ... }` — the URL is the secret,
and claude.ai then has nothing to configure). Without one of the two, a `401` makes
claude.ai start an OAuth flow that is bound to fail.

**If your reverse proxy runs in a Docker container** (instead of the systemd
Caddy above): it cannot reach the host's `127.0.0.1`. Set
`PENSINE_BIND_HOST=<bridge gateway>` (e.g. `172.18.0.1`) in `.env`,
point the vhost at it, and open the path in the firewall:
`ufw allow from <docker subnet> to <gateway> port 8300,8400 proto tcp`.
Also watch out for the Caddyfile bind mount: edit it **in place** (`cat >`,
an editor) — `sed -i` recreates the file and silently detaches the mount.

### Consolidation cron

The cron lines write to the logs folder (`/var/log/pensine/`
on a server, otherwise `PENSINE_LOG_DIR` or `PENSINE_DATA_DIR/logs` — see
`python3 -m pensine.config`). `install.sh` creates it, along with the media,
GeoNames and backup folders; without it, cron runs **nothing** (the redirection
fails before the command, silently). By hand:
```bash
sudo mkdir -p /var/log/pensine && sudo chown "$(whoami)" /var/log/pensine
```
Then `crontab -e`, and paste what `install.sh` printed (nightly at 03:00 +
REM on Sundays at 04:00 + monthly persona + daily `scripts/backup.sh`).

### Final checks

```bash
# Deposit API (401 expected without a token = OK; without a file, 422)
curl -s -o /dev/null -w '%{http_code}\n' https://your.domain/deposit -F "file=@/etc/hostname"   # 401
# Real deposit
source .env && curl -s https://your.domain/deposit \
  -H "Authorization: Bearer $PENSINE_DEPOSIT_TOKEN" \
  -F "file=@/etc/hostname" -F "note=test"                                        # {"ok":true,...}
# Dry-run consolidation
./.venv/bin/python consolidation/nightly.py
```

## Connecting to claude.ai

1. claude.ai → **Settings → Connectors → Add custom connector**
   → URL: `https://your.domain/mcp` (with the basicauth credentials if configured).
2. Create a **"Pensine" Claude project** and enable the connector in it. That is
   where your conversations, your logbook and your founding interview live.
3. Test it: "Use recall to search for "test" in my memory."

Any other client that speaks remote MCP connects the same way (see
[installer-chez-soi.md](installer-chez-soi.md) for ChatGPT).

## The two iOS shortcuts — ready to import

The fastest way: **import them, then replace two values**.

| Shortcut | Import link |
|---|---|
| Deposit (photo, voice note, PDF from the share sheet) | [Souvenance — Deposit](https://www.icloud.com/shortcuts/cbf7cb768b8d4b559ccdc21864891030) |
| Logbook (dictation, reviewed before sending) | [Souvenance — Daily log](https://www.icloud.com/shortcuts/0e633971aab04c43940e0d17f894ff18) |

After importing, open each shortcut → the **Get Contents of URL** action,
and replace:

- the **URL**: `https://YOUR-DOMAIN/deposit` (or `/log`) → your own URL;
- the **Authorization** header: `Bearer YOUR_DEPOSIT_TOKEN` → `Bearer ` followed by
  your `PENSINE_DEPOSIT_TOKEN` (from `.env`).

For the deposit shortcut, finally turn on "Show in Share Sheet" in its
settings. Nothing else to touch: method, form body and variables are already
in place.

### Building them by hand (if you prefer)

Shortcuts app → **+** → name it "Pensine":
1. **Receive** action: "Receive Any input from Share Sheet"
   (types: images, files, media)
2. **Get Contents of URL** action:
   - URL: `https://your.domain/deposit` — Method: **POST**
   - Headers: `Authorization` = `Bearer YOUR_PENSINE_DEPOSIT_TOKEN` (from `.env`)
   - Body: **Form** → field `file` = *Shortcut Input* (type File)
3. Shortcut settings → turn on "Show in Share Sheet"

Usage: WhatsApp voice note → long press → Forward → Share → **Pensine**.
Photo, PDF, voice memo: same thing. Two taps, and it is in the memory.

### Adding the place (optional, recommended)

A memory sits in space as much as in time. Photos already carry their GPS
coordinates; a shared voice memo does not (iOS strips them). To let each
deposit know where you were, in both shortcuts:

1. Before **Get Contents of URL**, add the **Get Current
   Location** action (iOS asks for permission once).
2. In the **Form** body, add two text fields:
   `lat` = *Current Location* → **Latitude**, and `lon` = *Current Location*
   → **Longitude** (tap the variable to pick the property).
3. (optional) a `place` text field: a place named in plain words ("at my
   parents'", "Goûter hut"), which takes precedence over the computed name.

The position stays on your server: the place name is computed locally
(`scripts/install_geonames.sh`, an offline copy of GeoNames), and no mapping service
learns where you were. Without these fields, everything works as before.
Tip: in Settings → Voice Memos, "Location-based Naming" names memos after the
street; Pensine uses it when it has nothing better.

## Getting started (the order that works)

1. **Founding interview** (docs/interview-fondatrice.md): 3 to 4 sessions in
   the assistant project, transcripts ingested with `scripts/ingest_interview.py` —
   it is what seeds the corpus. Without it, `recall` is empty.
2. **Daily logbook**: 2 or 3 minutes by voice in the assistant project
   ("daily_log: …") — 4 fields: what happened today, a decision or hesitation, how you feel, heading.
3. **Customise `constitution.yaml`** (shipped neutral, with no exclusions):
   patterns to exclude under `exclusions.motifs` (e.g. your professional
   sphere), then commit — the constitution is revised through Git.
4. Pensine deposits, whenever you like. The memory builds itself quietly.

## Advanced features (phase 2)

**Timeline web app** — `https://your.domain/app`: the visual dive back in.
A timeline of all deposits (audio playable in place, photos) and memories,
filterable by text, type and year. Password: `PENSINE_WEBAPP_PASSWORD`
(generated by `install.sh`).

**Temporal graph** — consolidation extracts entities and relations with their
validity periods; a fact that replaces another ("lives in") closes the
old edge without ever erasing it. `recall` returns a `graphe` section;
"what was true in 2024?" is a query, not a reconstruction.

**Mirror** — in your assistant: "use mirror with my question". Trajectory by
quarter, dominant entities, open contradictions — the system reports,
does not judge, and hands back control ("what do you make of it?").

**Choosing the embeddings engine** — `nomic` by default (768-d, ~500 MB:
fits in 4 GB of RAM); `bge-m3` (1024-d, ~2 GB resident: better
in French). To switch:
```bash
# in .env: PENSINE_EMBEDDING_BACKEND=bge-m3   (or nomic)
./.venv/bin/python scripts/reembed.py     # resizes and recomputes everything
sudo systemctl restart pensine-api pensine-mcp
```
Memories are recomputable projections: the operation is safe
and reversible.

**Voiceprints** (requires `--with-local`) — enrolment is an explicit
act:
```bash
./.venv/bin/python scripts/enroll_speaker.py --name "FirstName" sample.wav
```
Later cycles identify that voice in deposits. The sender of a
forwarded voice note (channel metadata) always takes precedence over ML.

**Persona** — every month, the compiler produces a proposed narrative
identity in `persona/propositions/` (chapters, themes, tensions, each
claim sourced and weighed). It only takes effect once you ratify it:
```bash
./.venv/bin/python scripts/ratify_persona.py 2026-XX-XX-persona.md
```

**Fidelity tests** — measure what the twin really knows (phase 2 threshold:
9/10 factual):
```bash
./.venv/bin/python scripts/fidelity_test.py generate --n 10
./.venv/bin/python scripts/fidelity_test.py run
./.venv/bin/python scripts/fidelity_test.py report   # score per domain
```

## Bringing in your history and going further

**Import your years of ChatGPT / Claude** — request your official exports
(Settings → Data), then:
```bash
./.venv/bin/python scripts/import_history.py ~/export/conversations.json
```
From the first night, `recall` knows years of you. Safe to re-run
(deduplication), filtered by your constitution.

**Import what the assistant remembers about you** (Claude/ChatGPT memory,
projects) — the unzipped export, or the memory copied into a `.md` file:
```bash
./.venv/bin/python scripts/import_vendor_memory.py ~/export/ --dry-run   # preview
./.venv/bin/python scripts/import_vendor_memory.py ~/export/
./.venv/bin/python scripts/vendor_mirror.py   # what it knows vs what you deposited
```
These are second-hand memories: they never count as much as a deposit.

**The logbook in one gesture** — an iOS "Log" shortcut, four actions:
1. **Dictate Text** (Stop Listening: *After Pause*)
2. **Ask for Input** (type Text, **Default Answer** = *Dictated
   Text*, multiple lines allowed) — the dictation shows up pre-filled and
   editable: you fix misheard words before sending
3. **Get Contents of URL**: `POST https://your.domain/log`,
   header `Authorization: Bearer <PENSINE_DEPOSIT_TOKEN>`, body
   **Form** → text field `text` = *Provided Input*
4. (optional) Add to Home Screen — the evening gesture

⚠️ The classic trap with both shortcuts: the **Request Body** must be
**Form** (not JSON, not File), otherwise the API answers 422 "Field
required". And the order of the actions matters: dictate *before* sending.

**The founding interview, run by the system** — in your assistant:
"start interview session 1"; the system asks the questions and ingests
itself at the end (`interview_save`).

**Landmarks for the temporal engine** — in your assistant: "add the landmark UTMB 2027 on
27 August" (the `landmark` tool). Races, moves, chapters: they
become the human coordinates of the time frame ("before or after
UTMB?").

**Time capsules** — "seal a capsule for 15 June 2027: …".
It resurfaces in your conversations on that day — never as a
notification.

**The Book of the Year** — `scripts/yearbook.py --year 2026`: your year
written from the memory, in markdown + printable HTML.

**100% local compute** — `PENSINE_LLM_BACKEND=ollama` (+
`PENSINE_OLLAMA_MODEL`): consolidation runs without any external
service. Vision is paused, everything else works.

**Encrypted off-site backup** — set `RESTIC_REPOSITORY` and
`RESTIC_PASSWORD` in `.env`: `backup.sh` pushes automatically to
B2/S3/SFTP with a 14-day / 3-month / 12-month rotation (the bound on the right to be forgotten,
see docs/oubli.md).

## Updating (new version of the kit)

Keep `.env`, `constitution.yaml` and `persona/`; replace the rest with the
new version (or `git pull`), then:
```bash
./install.sh            # same options as at install time (--with-local…):
                        # keeps .env, applies the migrations, reruns the tests
sudo systemctl restart pensine-api pensine-mcp   # install.sh does not restart
                                                 # services that are already running
```
Migrations (`scripts/migrate.py`) are idempotent: each one is applied
only once. If a version adds a step (e.g. GeoNames), it is listed
in `START-HERE.md`.

## Backup, export, reversibility

- `scripts/backup.sh`: SQL dump + rsync of the media — **durable formats**,
  readable in 30 years without the kit. Copy the folder off the VPS (restic/rclone).
- Full export at any time: the SQL dump **is** the export (events = the source
  of truth), media are ordinary files, the persona is
  markdown in Git.
- Stopping everything: `docker compose down` + disable the services. Your data
  stays in the Postgres volume and in `PENSINE_MEDIA_ROOT`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `recall` is empty | young corpus, consolidation has not run yet | ingest the interview, run `consolidation/nightly.py` by hand |
| `nightly_paused` in the audit log | `claude` CLI missing, not signed in, **or token revoked** (signing in again elsewhere can rotate it) | `claude /login` on the VPS — careful: the OAuth URL wraps over several lines in the terminal, copy all of it (the `org:create_api_key` scope must be complete) |
| consolidation never finishes, or opens a Claude window | the `claude` on the PATH is the **desktop app**, not the CLI (common on macOS) | `which -a claude`: if the first result is inside `Claude.app`, set `PENSINE_CLAUDE_BIN=/path/to/cli/claude` in `.env` |
| `media_skip` media in the audit log | WhisperX/Pillow/Docling missing | `./.venv/bin/pip install -e ".[local]"` — picked up on the next cycle |
| 503 on /deposit | token not configured | `PENSINE_DEPOSIT_TOKEN` in `.env`, restart |
| `install.sh`: "port already in use" | another Postgres is listening on 5432 | `PENSINE_DB_PORT=5433 ./install.sh` |
| claude.ai does not see the connector | /mcp not reachable over HTTPS | test `curl https://your.domain/mcp`; check Caddy |

The audit log (`SELECT * FROM audit_log ORDER BY at DESC LIMIT 50;`)
records everything the system has done — that is layer 7, it is there for that.
