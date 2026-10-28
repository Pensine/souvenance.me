"""Gate of the MCP server: a token, if PENSINE_MCP_TOKEN is set.

An intimate memory is not exposed bare. Three ways to present the token,
depending on what the client can do:

- `Authorization: Bearer <token>` header (Claude Code, scripted clients);
- secret path `/mcp/<token>` — custom connectors in claude.ai and ChatGPT
  send no header without OAuth, so the address alone carries the secret;
- `?token=<token>` parameter, for clients that keep the query string.

Without PENSINE_MCP_TOKEN, nothing changes: protection remains that of the
reverse proxy. Constant-time comparisons.
"""

import hmac
import json
from urllib.parse import parse_qsl, urlencode


def _same(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode(), expected.encode())


class TokenGate:
    """ASGI middleware in front of the MCP application (streamable HTTP)."""

    def __init__(self, app, token: str, path: str = "/mcp"):
        if not token:
            raise ValueError("TokenGate requires a non-empty token")
        self.app, self.token, self.path = app, token, path.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)  # lifespan

        path = scope.get("path", "")
        prefix = self.path + "/"
        if path.startswith(prefix):
            segment, _, rest = path[len(prefix):].partition("/")
            if segment and _same(segment, self.token):
                # secret path: the application only sees /mcp
                inner = self.path + (("/" + rest) if rest else "")
                scope = dict(scope, path=inner, raw_path=inner.encode())
                return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if auth[:7].lower() == "bearer " and _same(auth[7:].strip(), self.token):
            return await self.app(scope, receive, send)

        query = parse_qsl(scope.get("query_string", b"").decode("latin-1"),
                          keep_blank_values=True)
        given = [v for k, v in query if k == "token"]
        if given and _same(given[0], self.token):
            # the token goes no further than the gate
            rest = urlencode([(k, v) for k, v in query if k != "token"])
            scope = dict(scope, query_string=rest.encode())
            return await self.app(scope, receive, send)

        return await _refuse(scope, send)


async def _refuse(scope, send) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    body = json.dumps({"error": "MCP token missing or invalid"}).encode()
    await send({"type": "http.response.start", "status": 401, "headers": [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"www-authenticate", b'Bearer realm="pensine"'),
    ]})
    await send({"type": "http.response.body", "body": body})
