"""Pensine configuration — everything comes from the environment (.env on the VPS).

Generic by default: nothing here is specific to a given user.
Customization goes through environment variables and constitution.yaml.
"""

from __future__ import annotations  # the setup wizard runs under Python 3.9

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load ROOT/.env with no external dependency. The process environment
    keeps priority: a bare cron job and a systemd service (EnvironmentFile=)
    must see the same configuration — this is a field fix, the 3:30 a.m.
    consolidation crashed because cron did not load .env."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.split(" #")[0].strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")

# The user (first name used in the consolidation prompts). The default stays
# French: it is substituted into the French prompts.
OWNER_NAME = os.environ.get("PENSINE_OWNER_NAME", "l'utilisateur")

DATABASE_URL = os.environ.get(
    "PENSINE_DATABASE_URL", "postgresql://pensine:pensine@127.0.0.1:5432/pensine"
)

# Data folder (media, GeoNames, backups, logs). A single setting,
# PENSINE_DATA_DIR; each subfolder can still be overridden.
LEGACY_DATA_DIR = Path("/var/lib/pensine")


def default_data_dir(platform: str | None = None, home: Path | None = None,
                     legacy: Path = LEGACY_DATA_DIR, is_root: bool | None = None) -> Path:
    """Linux server (legacy folder present, or root): /var/lib/pensine,
    as on the original VPS. Otherwise the user's data folder:
    ~/Library/Application Support/Souvenance (macOS),
    $XDG_DATA_HOME/souvenance or ~/.local/share/souvenance (Linux and others)."""
    platform = platform or sys.platform
    home = home or Path.home()
    if is_root is None:
        is_root = getattr(os, "geteuid", lambda: -1)() == 0
    if platform.startswith("linux") and (legacy.exists() or is_root):
        return legacy
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Souvenance"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg) if xdg else home / ".local" / "share") / "souvenance"


DATA_DIR = Path(os.environ.get("PENSINE_DATA_DIR", "").strip() or default_data_dir())
# On the legacy installation, backups and logs keep their original locations
# (/var/backups, /var/log); elsewhere they live with the data, so that a
# single folder is enough to carry everything away.
_LEGACY = DATA_DIR == LEGACY_DATA_DIR


def _dir(var: str, sub: str, legacy: str | None = None) -> Path:
    explicit = os.environ.get(var, "").strip()
    if explicit:
        return Path(explicit)
    return Path(legacy) if (_LEGACY and legacy) else DATA_DIR / sub


# Layer 6 — media storage (encrypted filesystem in v1)
MEDIA_ROOT = _dir("PENSINE_MEDIA_ROOT", "media")
# Local copy of GeoNames: naming a place without telling anyone where you were
GEO_DIR = _dir("PENSINE_GEO_DIR", "geo")
BACKUP_DIR = _dir("PENSINE_BACKUP_DIR", "backups", legacy="/var/backups/pensine")
LOG_DIR = _dir("PENSINE_LOG_DIR", "logs", legacy="/var/log/pensine")
# Scope keys for crypto-shredding: OUTSIDE the database and its backups
KEYS_DIR = _dir("PENSINE_KEYS_DIR", "keys")
# … and their backup, separate from BACKUP_DIR: short retention (30 days)
KEYS_BACKUP_DIR = _dir("PENSINE_KEYS_BACKUP_DIR", "keys-backups")
# Language of voice notes: empty = automatic detection. Forcing a language
# makes Whisper TRANSLATE what is said in another one — an English memo came
# out in French, and the word-by-word scrolling no longer followed the voice.
TRANSCRIBE_LANGUAGE = os.environ.get("PENSINE_TRANSCRIBE_LANGUAGE", "").strip() or None
# Transcription engine: whisperx | faster-whisper | mlx-whisper | none.
# Empty = the first one installed, in that order (mlx-whisper: Apple Silicon Mac).
TRANSCRIBE_BACKEND = os.environ.get("PENSINE_TRANSCRIBE_BACKEND", "").strip().lower()
# Model, device (cpu | cuda) and precision. Empty = chosen according to the
# machine; WhisperX without a GPU keeps large-v3 / cpu / int8, as always.
WHISPER_MODEL = os.environ.get("PENSINE_WHISPER_MODEL", "").strip()
WHISPER_DEVICE = os.environ.get("PENSINE_WHISPER_DEVICE", "").strip().lower()
WHISPER_COMPUTE_TYPE = os.environ.get("PENSINE_WHISPER_COMPUTE_TYPE", "").strip()
# Cited evidence: 'modele' (default) rereads doubtful memories with the model;
# 'code' sticks to the free checks and marks doubtful ones "to verify".
# (The setting values 'modele' / 'code' are part of the config API and stay as is.)
VERIFY = os.environ.get("PENSINE_VERIFY", "modele").strip().lower()
# The person's timezone ("Europe/Paris"): a memory says "à 20 h" when the
# deposit is timestamped 18:00 UTC. Empty: the machine's timezone.
TIMEZONE = os.environ.get("PENSINE_TIMEZONE", "").strip() or None
# Severity of the evidence filter: 'defaut' (default), 'strict' (a doubtful
# memory not confirmed by the reread is rejected) or 'desactive' (annotate
# without filtering).
EVIDENCE_SEVERITY = os.environ.get("PENSINE_EVIDENCE_SEVERITY", "defaut").strip().lower()
# Modality check in the cascade (pensine/modality.py): 'signaler' ("flag") sends
# for reread a memory whose excerpt is conditional, future, negated, reported…
# while it asserts an accomplished fact. 'off' (default): previous behavior.
EVIDENCE_MODALITY = os.environ.get("PENSINE_EVIDENCE_MODALITY", "off").strip().lower()

# Real erasure (crypto-shredding, pensine/shred.py). Disabled by default:
# when enabled, each new deposit is encrypted under a scope key, kept outside
# the database; forgetting = destroying the key. Earlier deposits stay in clear.
SHRED_ENABLED = os.environ.get("PENSINE_SHRED", "0") == "1"
# Raw candidates from each night (before the evidence cascade), to measure
# the recall / invention frontier on a real database. Retention in days;
# 0 = keep nothing. Capped like backups: one year at most.
CANDIDATES_RETENTION_DAYS = min(365, int(os.environ.get(
    "PENSINE_CANDIDATES_RETENTION_DAYS", "365") or 0))

# Token of the iOS "Pensine" shortcut (POST /deposit) — mandatory in prod
PENSINE_TOKEN = os.environ.get("PENSINE_DEPOSIT_TOKEN", "")

# MCP server token (streamable HTTP). Empty = no application-level check
# (protection at the reverse proxy, as before). Set: Bearer header, secret
# path /mcp/<token> (claude.ai / ChatGPT connectors) or ?token=.
MCP_TOKEN = os.environ.get("PENSINE_MCP_TOKEN", "").strip()

# Secret for temporary signed media links (deep dive `recall(depth=source)`)
MEDIA_LINK_SECRET = os.environ.get("PENSINE_MEDIA_LINK_SECRET", "")
MEDIA_LINK_TTL_S = int(os.environ.get("PENSINE_MEDIA_LINK_TTL_S", "900"))  # 15 min

# Public URL of the Pensine API (to build the deep-dive links)
PUBLIC_BASE_URL = os.environ.get("PENSINE_PUBLIC_BASE_URL", "http://127.0.0.1:8300")

# Local embeddings. If unavailable, recall degrades to full-text search.
EMBEDDINGS_ENABLED = os.environ.get("PENSINE_EMBEDDINGS", "1") == "1"
# Backend: 'nomic' (768-d, ~500 MB of RAM — default, fits on a small VPS)
# or 'bge-m3' (1024-d, ~2 GB — better in French, needs RAM).
# Switching backend requires migrating the dimension of memories.embedding
# AND recomputing the vectors (the memories stay, the vectors are recomputable).
EMBEDDING_BACKEND = os.environ.get("PENSINE_EMBEDDING_BACKEND", "nomic")
_DEFAULT_MODELS = {"nomic": "nomic-ai/nomic-embed-text-v1.5", "bge-m3": "BAAI/bge-m3"}
EMBEDDING_MODEL = os.environ.get("PENSINE_EMBEDDING_MODEL",
                                 _DEFAULT_MODELS.get(EMBEDDING_BACKEND, ""))
EMBEDDING_DIM = int(os.environ.get("PENSINE_EMBEDDING_DIM",
                                   "1024" if EMBEDDING_BACKEND == "bge-m3" else "768"))

# Search: 'hybrid' (vector + full-text merged, default) or 'vector'
# (the old behavior: vector only, full-text as a mere fallback).
SEARCH_MODE = os.environ.get("PENSINE_SEARCH", "hybrid").strip().lower()
# Local reranker (cross-encoder): empty = disabled. It rereads the best
# candidates with the question in front of it. Measurements and RAM per model:
# research/evals/rappel/. Examples: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
# (multilingual, ~0.5 GB), BAAI/bge-reranker-v2-m3 (multilingual, ~2.3 GB).
RERANKER_MODEL = os.environ.get("PENSINE_RERANKER", "").strip()
RERANK_TOP = int(os.environ.get("PENSINE_RERANK_TOP", "30"))
# 'cpu' by default: everything must work without a graphics card; 'mps' or
# 'cuda' speed things up when available.
RERANKER_DEVICE = os.environ.get("PENSINE_RERANK_DEVICE", "cpu").strip()

# Compute adapter: 'claude-cli' (Max/Pro subscription), 'api',
# 'ollama' (100% local), 'fake' (tests)
LLM_BACKEND = os.environ.get("PENSINE_LLM_BACKEND", "claude-cli")
# 'openai': any /v1/chat/completions-compatible server (OpenAI, Mistral,
# LM Studio, mlx_lm.server, vLLM, llama.cpp, Ollama /v1…) — its model has no
# reasonable default, it must be named.
LLM_MODEL = os.environ.get("PENSINE_LLM_MODEL",
                           "" if LLM_BACKEND == "openai" else "claude-sonnet-5-5")
LLM_BASE_URL = os.environ.get("PENSINE_LLM_BASE_URL", "").strip()
LLM_API_KEY = os.environ.get("PENSINE_LLM_API_KEY", "").strip()
# Response cap: some local servers cut off at 512 tokens by default, too
# short for a batch of memories in JSON.
LLM_MAX_TOKENS = int(os.environ.get("PENSINE_LLM_MAX_TOKENS", "8192"))
# Structured output: 'auto' asks the backend for a JSON object whenever the
# caller expects one (OpenAI-compatible `response_format`, Ollama `format`),
# falling back silently when the server refuses it; 'off' never asks.
LLM_JSON_MODE = os.environ.get("PENSINE_LLM_JSON_MODE", "auto").strip().lower()

# Consolidation robustness (consolidation/nightly.py). A night whose answer
# cannot be read is asked again, stricter (ATTEMPTS calls per batch in all),
# then split in halves down to single deposits. A deposit that still fails
# stays pending for the next night: never lost, never blocking the others.
CONSOLIDATION_ATTEMPTS = int(os.environ.get("PENSINE_CONSOLIDATION_ATTEMPTS", "2"))
# Upper bound on deposits sent in one call, 0 = no bound (the whole night,
# split only on failure). Small local models may do better with 4-6.
CONSOLIDATION_MAX_EVENTS = int(os.environ.get("PENSINE_CONSOLIDATION_MAX_EVENTS", "0"))
# Language memories are written in: 'source' = the language of the deposit
# they come from (detected per deposit, pensine/language.py); or a fixed
# code ('fr', 'en'…) to write everything in one language.
MEMORY_LANGUAGE = os.environ.get("PENSINE_MEMORY_LANGUAGE", "source").strip().lower()
# Model for describing images (openai and ollama backends); empty = the same
# as for text. A model without vision makes the description fail, and the
# photo stays pending — a pause, not a loss.
VISION_MODEL = os.environ.get("PENSINE_VISION_MODEL", "").strip()
# Path to the CLI binary. Set it when `claude` on the PATH is not the CLI:
# the desktop app installs an executable of the same name that opens a window
# instead of answering — consolidation then waits for nothing.
CLAUDE_BIN = os.environ.get("PENSINE_CLAUDE_BIN", "claude")
ANTHROPIC_API_KEY = os.environ.get("PENSINE_ANTHROPIC_API_KEY", "")
OLLAMA_URL = os.environ.get("PENSINE_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("PENSINE_OLLAMA_MODEL", "qwen3")

# Executable constitution (layer 7)
CONSTITUTION_PATH = Path(os.environ.get("PENSINE_CONSTITUTION",
                                        str(ROOT / "constitution.yaml")))

# Perceptors
# Personal calendar: private ICS URL(s), comma-separated
CALENDAR_ICS_URLS = [u.strip() for u in
                     os.environ.get("PENSINE_CALENDAR_ICS_URLS", "").split(",")
                     if u.strip()]
# Personal mail (phase 2, disabled while PENSINE_IMAP_HOST is empty)
IMAP_HOST = os.environ.get("PENSINE_IMAP_HOST", "")
IMAP_USER = os.environ.get("PENSINE_IMAP_USER", "")
IMAP_PASSWORD = os.environ.get("PENSINE_IMAP_PASSWORD", "")
IMAP_FOLDER = os.environ.get("PENSINE_IMAP_FOLDER", "INBOX")


def shell_paths() -> str:
    """The resolved folders, as shell assignments (backup, GeoNames,
    cron): a single resolution rule, the one here."""
    import shlex
    pairs = {"PENSINE_DATA_DIR": DATA_DIR, "PENSINE_MEDIA_ROOT": MEDIA_ROOT,
             "PENSINE_GEO_DIR": GEO_DIR, "PENSINE_BACKUP_DIR": BACKUP_DIR,
             "PENSINE_LOG_DIR": LOG_DIR, "PENSINE_KEYS_DIR": KEYS_DIR,
             "PENSINE_KEYS_BACKUP_DIR": KEYS_BACKUP_DIR}
    return "\n".join(f"{k}={shlex.quote(str(v))}" for k, v in pairs.items())


if __name__ == "__main__":
    # eval "$(python3 -m pensine.config)" in shell scripts
    print(shell_paths())
