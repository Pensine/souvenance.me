# Connecting the Pensine to Claude

A single interface: you talk to Claude (web, mobile, voice), which carries the memory
through this MCP server. There are two modes, depending on the client.

## claude.ai / mobile app (remote connector) — the target mode

claude.ai requires a **remote** MCP server (streamable HTTP), reachable over HTTPS.

On the VPS:

```bash
PENSINE_MCP_TRANSPORT=streamable-http \
FASTMCP_HOST=127.0.0.1 FASTMCP_PORT=8400 \
python -m pensine.mcp_server
```

Behind the reverse proxy (Caddy/nginx), expose `https://pensine.example.org/mcp`
→ `127.0.0.1:8400`.

Then in claude.ai: **Settings → Connectors → Add custom connector**
→ URL `https://pensine.example.org/mcp`. Next, create the
**"Pensine" Claude project** and enable the connector in it: that is where
the conversations, the logbook and the founding interview live.

> Security: never expose the MCP server without authentication. The
> simplest way: set `PENSINE_MCP_TOKEN` (scripts/setup.py generates it). The
> server then requires the token — either as an `Authorization: Bearer <token>`
> header, or in the address: `https://pensine.example.org/mcp/<token>`, which is the form
> to paste into a claude.ai or ChatGPT connector, since those send no header.
> Without a token, protection is left to the reverse proxy (mTLS, IP allowlist).
> Intimate memory never leaves without access control.

## Claude Code / Claude Desktop (stdio, for development)

```bash
claude mcp add pensine -- python -m pensine.mcp_server
```

or in the Desktop config:

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

## "Pensine" iOS Shortcut (deposits, outside MCP)

Share sheet → shortcut → `POST https://pensine.example.org/deposit`
(header `Authorization: Bearer $PENSINE_DEPOSIT_TOKEN`, field `file`,
optional fields `note`, `captured_at`, `sender`). Two taps between
"this voice note matters" and "it's in the Pensine".
