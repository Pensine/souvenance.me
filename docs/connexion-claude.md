# Connecter la Pensine à Claude

Interface unique : on parle à Claude (web, mobile, voix), qui porte la mémoire
via ce serveur MCP. Deux modes selon le client.

## claude.ai / app mobile (connecteur distant) — le mode cible

claude.ai exige un serveur MCP **distant** (streamable HTTP), accessible en HTTPS.

Sur le VPS :

```bash
PENSINE_MCP_TRANSPORT=streamable-http \
FASTMCP_HOST=127.0.0.1 FASTMCP_PORT=8400 \
python -m pensine.mcp_server
```

Derrière le reverse proxy (Caddy/nginx), exposer `https://pensine.example.org/mcp`
→ `127.0.0.1:8400`.

Puis dans claude.ai : **Paramètres → Connecteurs → Ajouter un connecteur
personnalisé** → URL `https://pensine.example.org/mcp`. Créer ensuite le
**projet Claude « Pensine »** et y activer le connecteur : c'est là que vivent
les conversations, le log de bord et l'interview fondatrice.

> Sécurité v1 : ne pas exposer le serveur MCP sans authentification. Au choix :
> auth au niveau du reverse proxy (mTLS, IP allowlist) ou OAuth du SDK MCP.
> La mémoire intime ne sort jamais sans contrôle d'accès.

## Claude Code / Claude Desktop (stdio, pour développer)

```bash
claude mcp add pensine -- python -m pensine.mcp_server
```

ou dans la config Desktop :

```json
{
  "mcpServers": {
    "pensine": {
      "command": "python",
      "args": ["-m", "pensine.mcp_server"],
      "env": { "PENSINE_DATABASE_URL": "postgresql://pensine:…@127.0.0.1:5432/pensine" }
    }
  }
}
```

## Raccourci iOS « Pensine » (dépôt, hors MCP)

Share sheet → raccourci → `POST https://pensine.example.org/deposit`
(en-tête `Authorization: Bearer $PENSINE_DEPOSIT_TOKEN`, champ `file`,
champs optionnels `note`, `captured_at`, `sender`). Deux taps entre
« ce vocal compte » et « c'est dans la Pensine ».
