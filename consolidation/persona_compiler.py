#!/usr/bin/env python3
"""Le compilateur de persona (pièce 2 du §7) — la plus originale et la plus
précieuse : flux de mémoires → identité narrative structurée (McAdams).

Produit une PROPOSITION complète dans persona/propositions/ :
chapitres, tournants, thèmes, tensions assumées, style de décision —
chaque affirmation avec confiance calibrée et mémoires sources.
JAMAIS auto-ratifiée : `scripts/ratify_persona.py` installe la version
que l'utilisateur a relue et amendée. L'utilisateur est l'auteur final.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, llm  # noqa: E402
from pensine.governor import Governor  # noqa: E402

PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "persona" / "propositions"

PROMPT = """Tu es le compilateur de persona du Jumeau de {owner}.

Matériau : les mémoires consolidées (avec confiance et importance), le graphe
des relations actives, et le persona actuellement ratifié (s'il existe).

```json
{material}
```

Compile une IDENTITÉ NARRATIVE structurée (McAdams) — pas une liste de traits,
une histoire :

## Chapitres
Les périodes de vie visibles dans le corpus, avec leurs tournants.

## Thèmes
Les fils rouges qui traversent les chapitres (3-6, pas plus).

## Tensions assumées
Les polarités qui coexistent sans se résoudre — les nommer, pas les lisser.

## Style de décision
Comment les décisions se prennent réellement (d'après les mémoires
procédurales et les hésitations loggées).

## Relations structurantes
Qui compte et quel rôle (d'après le graphe) — règle des tiers : le rôle dans
SA vie, jamais l'intimité des autres.

Règles absolues :
- Chaque affirmation porte [confiance: 0.x] et cite ses mémoires sources [ids].
- Ce qui n'est pas fondé sur le corpus n'existe pas — pas d'invention.
- Aucun jugement, aucun écart présupposé, aucune norme.
- Si le corpus est trop mince pour une section, écris « corpus insuffisant ».

{constitution}

Réponds en markdown, directement le document (il sera relu et amendé par
{owner} avant ratification — c'est une proposition, pas une vérité)."""


def gather_material(conn) -> dict | None:
    memories = conn.execute(
        """
        SELECT id, type, content, confidence, importance, valid_from
        FROM memories WHERE superseded_by IS NULL
        ORDER BY importance DESC LIMIT 120
        """
    ).fetchall()
    if len(memories) < 10:
        return None
    relations = conn.execute(
        """
        SELECT s.name AS subject, r.predicate, o.name AS object, r.valid_from
        FROM relations r
        JOIN entities s ON s.id = r.subject_id
        JOIN entities o ON o.id = r.object_id
        WHERE r.valid_to IS NULL ORDER BY r.valid_from LIMIT 60
        """
    ).fetchall()
    persona_dir = Path(__file__).resolve().parent.parent / "persona"
    current = [f.read_text(encoding="utf-8")
               for f in sorted(persona_dir.glob("*.md")) if f.name != "README.md"]
    return {
        "memories": [dict(m) for m in memories],
        "relations_actives": [dict(r) for r in relations],
        "persona_ratifie": "\n\n".join(current) or "(aucun encore)",
    }


def main() -> None:
    governor = Governor()
    with db.connection() as conn:
        material = gather_material(conn)
        if material is None:
            db.audit(conn, "consolidation", "persona_noop", {})
            conn.commit()
            print("Corpus trop jeune pour compiler un persona (< 10 mémoires).")
            return
    prompt = PROMPT.format(
        owner=config.OWNER_NAME,
        material=json.dumps(material, ensure_ascii=False, default=str),
        constitution=governor.constitution_text(),
    )
    try:
        output = llm.complete(prompt)
    except llm.LLMUnavailable as exc:
        print(f"Compilation en pause ({exc}).")
        return

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = PROPOSALS_DIR / f"{stamp}-persona.md"
    out.write_text(output, encoding="utf-8")
    with db.connection() as conn:
        db.audit(conn, "consolidation", "persona_compiled", {"proposal": str(out)})
        conn.commit()
    print(f"Proposition de persona : {out}\n"
          f"Relisez, amendez, puis : scripts/ratify_persona.py {out.name}")


if __name__ == "__main__":
    main()
