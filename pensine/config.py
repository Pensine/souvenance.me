"""Configuration de la Pensine — tout vient de l'environnement (.env sur le VPS).

Générique par défaut : rien ici n'est propre à un utilisateur donné.
La personnalisation passe par les variables d'environnement et constitution.yaml.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Charge ROOT/.env sans dépendance externe. L'environnement du process
    garde la priorité : un cron nu et un service systemd (EnvironmentFile=)
    doivent voir la même configuration — c'est un correctif de terrain, la
    consolidation de 3h30 plantait car le cron ne chargeait pas .env."""
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

# L'utilisateur (prénom utilisé dans les prompts de consolidation)
OWNER_NAME = os.environ.get("PENSINE_OWNER_NAME", "l'utilisateur")

DATABASE_URL = os.environ.get(
    "PENSINE_DATABASE_URL", "postgresql://pensine:pensine@127.0.0.1:5432/pensine"
)

# Couche 6 — stockage média (filesystem chiffré en v1)
MEDIA_ROOT = Path(os.environ.get("PENSINE_MEDIA_ROOT", "/var/lib/pensine/media"))

# Token du raccourci iOS « Pensine » (POST /deposit) — obligatoire en prod
PENSINE_TOKEN = os.environ.get("PENSINE_DEPOSIT_TOKEN", "")

# Secret des liens médias signés temporaires (replongée `recall(depth=source)`)
MEDIA_LINK_SECRET = os.environ.get("PENSINE_MEDIA_LINK_SECRET", "")
MEDIA_LINK_TTL_S = int(os.environ.get("PENSINE_MEDIA_LINK_TTL_S", "900"))  # 15 min

# URL publique de l'API Pensine (pour construire les liens de replongée)
PUBLIC_BASE_URL = os.environ.get("PENSINE_PUBLIC_BASE_URL", "http://127.0.0.1:8300")

# Embeddings locaux. Si indisponibles, recall dégrade en recherche plein-texte.
EMBEDDINGS_ENABLED = os.environ.get("PENSINE_EMBEDDINGS", "1") == "1"
# Backend : 'nomic' (768-d, ~500 Mo de RAM — défaut, tient sur un petit VPS)
# ou 'bge-m3' (1024-d, ~2 Go — meilleur en français, exige de la RAM).
# Changer de backend impose de migrer la dimension de memories.embedding
# ET de recalculer les vecteurs (les mémoires restent, elles sont recalculables).
EMBEDDING_BACKEND = os.environ.get("PENSINE_EMBEDDING_BACKEND", "nomic")
_DEFAULT_MODELS = {"nomic": "nomic-ai/nomic-embed-text-v1.5", "bge-m3": "BAAI/bge-m3"}
EMBEDDING_MODEL = os.environ.get("PENSINE_EMBEDDING_MODEL",
                                 _DEFAULT_MODELS.get(EMBEDDING_BACKEND, ""))
EMBEDDING_DIM = int(os.environ.get("PENSINE_EMBEDDING_DIM",
                                   "1024" if EMBEDDING_BACKEND == "bge-m3" else "768"))

# Adaptateur compute : 'claude-cli' (abonnement Max/Pro), 'api',
# 'ollama' (100 % local), 'fake' (tests)
LLM_BACKEND = os.environ.get("PENSINE_LLM_BACKEND", "claude-cli")
LLM_MODEL = os.environ.get("PENSINE_LLM_MODEL", "claude-sonnet-5")
ANTHROPIC_API_KEY = os.environ.get("PENSINE_ANTHROPIC_API_KEY", "")
OLLAMA_URL = os.environ.get("PENSINE_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("PENSINE_OLLAMA_MODEL", "qwen3")

# Constitution exécutable (couche 7)
CONSTITUTION_PATH = Path(os.environ.get("PENSINE_CONSTITUTION",
                                        str(ROOT / "constitution.yaml")))

# Percepteurs
# Agenda personnel : URL(s) ICS privée(s), séparées par des virgules
CALENDAR_ICS_URLS = [u.strip() for u in
                     os.environ.get("PENSINE_CALENDAR_ICS_URLS", "").split(",")
                     if u.strip()]
# Mails personnels (phase 2, désactivé tant que PENSINE_IMAP_HOST est vide)
IMAP_HOST = os.environ.get("PENSINE_IMAP_HOST", "")
IMAP_USER = os.environ.get("PENSINE_IMAP_USER", "")
IMAP_PASSWORD = os.environ.get("PENSINE_IMAP_PASSWORD", "")
IMAP_FOLDER = os.environ.get("PENSINE_IMAP_FOLDER", "INBOX")
