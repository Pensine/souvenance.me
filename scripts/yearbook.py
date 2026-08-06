#!/usr/bin/env python3
"""Le Livre de l'année — l'autobiographie dynamique rendue imprimable.

Génère à la demande (jamais poussé) un livre markdown + HTML imprimable
depuis la mémoire d'une année : chapitres par saison, jalons, décisions,
ce qui a changé. La voix du présent, avant que le futur ne réécrive.

Usage : yearbook.py --year 2026
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, llm  # noqa: E402
from pensine.governor import Governor  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "persona" / "propositions"

PROMPT = """Tu écris le Livre de l'année {year} de {owner}, à partir de sa mémoire
consolidée. Pas une liste : un récit — sa voix, ses mots, au présent de
l'année vécue.

Matériau (mémoires, jalons, graphe, contradictions de l'année) :

```json
{material}
```

Structure :
# {year}
Une page d'ouverture : le ton de l'année en quelques lignes.
## Hiver / Printemps / Été / Automne
Un chapitre par saison vécue : les faits qui comptent, les décisions
(et leurs hésitations), les lieux, les gens (règle des tiers : leur rôle
dans SA vie, jamais leur intimité).
## Ce qui a changé
Les croyances ouvertes puis fermées, les caps pris — d'après le graphe.
## Ce que je veux me rappeler
5-10 lignes que {owner}-de-2036 sera heureux de relire.

Règles : uniquement ce qui est dans le matériau (aucune invention),
aucun jugement, aucune norme. {constitution}

Réponds en markdown, directement le livre."""

HTML_WRAP = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font:19px/1.7 Georgia,serif;max-width:38rem;margin:3rem auto;padding:0 1.5rem;color:#222}}
h1{{font-size:3.5rem;text-align:center;margin:4rem 0}}
h2{{margin-top:3rem;border-bottom:1px solid #ccc;padding-bottom:.3rem}}
@media print{{body{{font-size:12pt}}h1{{page-break-before:always}}}}
</style></head><body>{body}</body></html>"""


def gather(conn, year: int) -> dict | None:
    memories = conn.execute(
        """SELECT type, content, importance, valid_from FROM memories
           WHERE superseded_by IS NULL
             AND extract(year FROM valid_from) = %s
           ORDER BY importance DESC LIMIT 150""", (year,)).fetchall()
    if len(memories) < 8:
        return None
    landmarks = conn.execute(
        "SELECT name, at_date, kind FROM landmarks "
        "WHERE extract(year FROM at_date) = %s ORDER BY at_date", (year,)).fetchall()
    changed = conn.execute(
        """SELECT s.name AS subject, r.predicate, o.name AS object,
                  r.valid_from, r.valid_to
           FROM relations r
           JOIN entities s ON s.id = r.subject_id
           JOIN entities o ON o.id = r.object_id
           WHERE extract(year FROM r.valid_from) = %s
              OR extract(year FROM r.valid_to) = %s
           ORDER BY r.valid_from LIMIT 60""", (year, year)).fetchall()
    stats = conn.execute(
        """SELECT count(*) AS deposits FROM events
           WHERE kind = 'deposit' AND extract(year FROM occurred_at) = %s""",
        (year,)).fetchone()
    return {"memories": [dict(m) for m in memories],
            "jalons": [dict(l) for l in landmarks],
            "graphe_changements": [dict(c) for c in changed],
            "depots_pensine": stats["deposits"]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    args = p.parse_args()

    with db.connection() as conn:
        material = gather(conn, args.year)
        if material is None:
            sys.exit(f"Corpus {args.year} trop mince (< 8 mémoires) — "
                     "le livre attendra.")

    prompt = PROMPT.format(
        year=args.year, owner=config.OWNER_NAME,
        material=json.dumps(material, ensure_ascii=False, default=str),
        constitution=Governor().constitution_text(),
    )
    try:
        book = llm.complete(prompt)
    except llm.LLMUnavailable as exc:
        sys.exit(f"Compute indisponible ({exc}) — réessayez plus tard, "
                 "rien n'est perdu.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = OUT_DIR / f"livre-{args.year}.md"
    md.write_text(book, encoding="utf-8")
    # version imprimable (markdown minimal → HTML)
    import html as html_mod
    paras = []
    for line in book.splitlines():
        if line.startswith("# "):
            paras.append(f"<h1>{html_mod.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            paras.append(f"<h2>{html_mod.escape(line[3:])}</h2>")
        elif line.strip():
            paras.append(f"<p>{html_mod.escape(line)}</p>")
    (OUT_DIR / f"livre-{args.year}.html").write_text(
        HTML_WRAP.format(title=f"Livre {args.year}", body="\n".join(paras)),
        encoding="utf-8")

    with db.connection() as conn:
        db.audit(conn, "mcp", "yearbook", {"year": args.year, "path": str(md)})
        conn.commit()
    print(f"Livre {args.year} : {md} (+ .html imprimable)")


if __name__ == "__main__":
    main()
