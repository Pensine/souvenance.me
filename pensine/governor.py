"""The constitutional governor (layer 7) — executable enforcement.

The constitution (constitution.yaml, versioned in Git) is checked by code:
event filtering at ingestion (exclusion perimeter), refusal of outbound
actions in v1, injection of the constitutional text into the consolidation
prompts. Every refusal is logged in the audit trail.
"""

import json
from pathlib import Path

import yaml

from . import config, db

_DEFAULT = {
    "version": 1,
    "regle_du_silence": True,
    "actions_sortantes": "interdites",
    "exclusions": {"sources": [], "motifs": []},
    "regle_des_tiers": "synthese",
    "persona_auto_ratification": False,
}


class Governor:
    def __init__(self, path: Path | None = None):
        self.path = path or config.CONSTITUTION_PATH
        if self.path.exists():
            loaded = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            self.rules = {**_DEFAULT, **loaded}
        else:
            self.rules = dict(_DEFAULT)

    # -- Exclusion perimeter -------------------------------------------------
    def event_allowed(self, source: str, payload: dict) -> tuple[bool, str]:
        exclusions = self.rules.get("exclusions") or {}
        if source in (exclusions.get("sources") or []):
            return False, f"excluded source: {source}"
        blob = json.dumps(payload, ensure_ascii=False).lower()
        for motif in exclusions.get("motifs") or []:
            if motif.lower() in blob:
                return False, f"excluded pattern: {motif}"
        return True, ""

    def filter_events(self, conn, events: list[dict]) -> list[dict]:
        """Drop events outside the perimeter, logging each rejection."""
        kept = []
        for e in events:
            ok, reason = self.event_allowed(e["source"], e["payload"])
            if ok:
                kept.append(e)
            else:
                db.audit(conn, "governor", "event_rejected",
                         {"source": e["source"], "reason": reason})
        return kept

    # -- Actions ---------------------------------------------------------------
    def action_allowed(self, action: str) -> bool:
        """v1: inbound only. Everything that goes out (sending, notification,
        publication) is refused, whatever the request."""
        outbound = {"send", "notify", "publish", "post", "email", "message"}
        if any(action.lower().startswith(v) for v in outbound):
            return False
        return True

    def check_action(self, conn, actor: str, action: str) -> None:
        if not self.action_allowed(action):
            db.audit(conn, "governor", "action_refused",
                     {"actor": actor, "action": action})
            raise PermissionError(
                f"Constitution: outbound action refused ({action}) — "
                "v1 is inbound-only, and the silence rule is absolute."
            )

    # -- Injection into prompts -------------------------------------------
    def constitution_text(self) -> str:
        # The returned text is injected into the (French) consolidation prompts,
        # so it stays in French.
        exclusions = self.rules.get("exclusions") or {}
        lines = [
            "Contraintes constitutionnelles (non négociables) :",
            "- Aucun jugement : rapporte, ne prescris pas de norme.",
            "- Règle des tiers : les conversations intimes des autres sont "
            "synthétisées, jamais archivées verbatim.",
        ]
        motifs = exclusions.get("motifs") or []
        if motifs:
            lines.append(
                "- Périmètre d'exclusion : ignore tout contenu se rapportant à : "
                + ", ".join(motifs) + "."
            )
        sources = exclusions.get("sources") or []
        if sources:
            lines.append("- Sources bannies (ne jamais consolider) : "
                         + ", ".join(sources) + ".")
        lines.append("- Le persona n'est jamais auto-ratifié : l'utilisateur "
                     "est l'auteur final.")
        return "\n".join(lines)
