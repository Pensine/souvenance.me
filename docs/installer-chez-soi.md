# Installing Souvenance at home

Your memory runs on a machine you own: a Mac, a Linux PC or a NAS. Allow
20 minutes; no technical knowledge needed. Everything goes through
**Docker**, a free program that runs ready-made applications ("containers")
without installing anything else.

You need:

- a machine that stays on at night (the memory is tidied up around 3:30 am);
- about 10 GB of free space;
- an AI model: a subscription you already have (for example a Claude plan), an API key
  (Anthropic, OpenAI, Mistral…), or a model already running on your machine (LM Studio, Ollama…).

## 1. Install Docker

- **Mac**: install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  or [OrbStack](https://orbstack.dev) (lighter), and open it once.
- **Linux**: `curl -fsSL https://get.docker.com | sh`, then log out
  and back in.
- **Synology NAS**: Package Center → install **Container Manager**.

## 2. Get Souvenance and run the setup assistant

Open the Terminal (Mac: Applications → Utilities → Terminal):

```bash
git clone <repository-url> souvenance
cd souvenance
python3 scripts/setup.py
```

The assistant asks three questions — which AI, your first name, your public
address (leave it empty for now) —, tries the AI with one tiny call,
creates every password and writes the `.env` file. It is safe to run again:
secrets that already exist are kept.

> **Claude subscription**: the assistant asks for a token. In another
> Terminal, run `claude setup-token` (the Claude CLI must be installed
> on this machine), sign in, and paste the token it shows.
>
> **Local model**: give the server address, for example
> `http://localhost:1234/v1` (LM Studio) or `http://localhost:11434/v1`
> (Ollama). The assistant rewrites it so that it stays reachable from Docker.

Then start everything:

```bash
docker compose up -d --build
```

The first build takes 5 to 15 minutes. After that, the memory restarts on
its own with the machine.

**No Python on the machine** (some NAS): run the assistant in a
container, from the `souvenance` folder:

```bash
docker run --rm -it -v "$PWD:/app" -w /app python:3.12-slim python scripts/setup.py
```

**Synology, without a Terminal**: run the assistant on your computer,
copy the `souvenance` folder (with its `.env`) to a NAS share, then
Container Manager → Project → Create → pick that folder: the
`docker-compose.yml` file is used as is.

## 3. A public address (Cloudflare tunnel)

claude.ai, ChatGPT and the iPhone shortcut need to reach your machine
from the Internet, over HTTPS. A Cloudflare tunnel does this without opening
a port on your router. You need a domain name managed by Cloudflare (free
account).

1. Cloudflare dashboard → **Zero Trust → Networks → Tunnels →
   Create a tunnel** (type *Cloudflared*), name it, copy the **token**.
2. In the tunnel, add two **Public hostnames** on the same name
   (e.g. `memory.example.com`), in this order:
   - path `^/mcp` → service `http://mcp:8400`;
   - no path → service `http://api:8300`.
3. Run the assistant again with that address and token, then restart:

```bash
python3 scripts/setup.py --public-url https://memory.example.com --tunnel-token <token>
docker compose up -d
```

## 4. Connect Claude or ChatGPT

The assistant prints an address of the form
`https://memory.example.com/mcp/<key>`. It contains your key: keep it
to yourself.

- **Claude** (web, mobile, desktop): Settings → Connectors → Add custom
  connector → paste the address.
- **ChatGPT**: Settings → Connectors (developer mode) → Create →
  paste the address, with no authentication.
- **Claude Code**: `claude mcp add --transport http souvenance <address>`.

The iPhone shortcut (drop in a voice note, a photo, a PDF) uses the
`…/deposit` address and the header printed by the assistant — details in
[connexion-claude.md](connexion-claude.md).

## Troubleshooting

| Symptom | What to do |
|---|---|
| The assistant reports a failure for the AI | Check the key, or that the local model is running; run the assistant again. Later: `docker compose run --rm api python -m pensine.setup_wizard check` |
| `port is already allocated` | Another program is using the port. Run the assistant again: it picks a free one |
| claude.ai rejects the address | It needs the public HTTPS address (step 3), not `localhost` |
| Nothing happens at night | `docker compose logs nightly`; the time follows `TZ` in `.env` |
| Voice notes are not transcribed | `docker compose logs nightly`; transcription runs on the CPU, so a long voice note takes time |
| See what is going on | `docker compose ps` then `docker compose logs -f` |
| Update | `git pull && docker compose up -d --build` |

Your data lives in the Docker volumes `souvenance_data` (media,
daily backups, logs) and `pensine_pgdata` (the database). To see it as an
ordinary folder, set `SOUVENANCE_DATA=./data` in `.env` before the first start.
