#!/usr/bin/env python3
"""Harnais de fidélité (pièce 4 du §7) — sans mesure, pas de graduation.

Test factuel v1 (phase 2 : « réponses factuelles 9/10 ») :
1. `generate` : échantillonne des mémoires, fait produire des paires
   question/réponse-attendue fondées dessus
2. `run` : le jumeau répond À L'AVEUGLE — uniquement via recall (le contexte
   qu'un agent aurait), pas la mémoire source
3. un juge LLM compare réponse/attendu ; chaque essai est stocké dans
   `predictions` (context='fidelity:<domaine>')
4. `report` : score par domaine

Usage :
  fidelity_test.py generate --n 10        # crée le quiz du jour
  fidelity_test.py run                    # fait passer le test au jumeau
  fidelity_test.py report                 # scores cumulés par domaine
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, llm  # noqa: E402

QUIZ_PATH = Path(__file__).resolve().parent.parent / "persona" / "propositions" / "fidelity_quiz.json"

GEN_PROMPT = """Voici des mémoires consolidées du Jumeau de {owner} :

```json
{memories}
```

Produis {n} questions factuelles dont la réponse est ENTIÈREMENT contenue dans
ces mémoires (dates, lieux, décisions, personnes, faits). Pour chacune :
- "domain" : le domaine de vie (ex. "projets", "relations", "sport", "lieux")
- "question" : formulée comme {owner} se la poserait
- "expected" : la réponse attendue, brève, fondée sur les mémoires
- "source_memory_ids" : les ids utilisés

Réponds UNIQUEMENT en JSON : [{{"domain": "...", "question": "...", "expected": "...", "source_memory_ids": [..]}}]"""

ANSWER_PROMPT = """Tu es le Jumeau de {owner}. Réponds à cette question en te fondant
UNIQUEMENT sur le contexte de mémoire ci-dessous (résultat de recall). Si le
contexte ne suffit pas, réponds exactement : "je ne sais pas".

Question : {question}

Contexte recall :
```json
{context}
```

Réponds en une ou deux phrases, rien d'autre."""

JUDGE_PROMPT = """Compare la réponse du jumeau à la réponse attendue.

Question : {question}
Attendu : {expected}
Réponse du jumeau : {answer}

La réponse du jumeau contient-elle les faits essentiels de l'attendu ?
"je ne sais pas" compte comme incorrect mais honnête (pas d'hallucination).
Réponds UNIQUEMENT en JSON : {{"correct": true|false, "hallucination": true|false}}"""


def generate(n: int) -> None:
    with db.connection() as conn:
        memories = conn.execute(
            """
            SELECT id, type, content, valid_from FROM memories
            WHERE superseded_by IS NULL AND confidence >= 0.7
            ORDER BY md5(id::text || current_date::text) LIMIT 40
            """
        ).fetchall()
    if len(memories) < 5:
        sys.exit("Corpus trop jeune (< 5 mémoires fiables).")
    raw = llm.complete(GEN_PROMPT.format(
        owner=config.OWNER_NAME, n=n,
        memories=json.dumps([dict(m) for m in memories], ensure_ascii=False,
                            default=str)))
    quiz = llm.extract_json(raw)
    QUIZ_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUIZ_PATH.write_text(json.dumps(quiz, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"{len(quiz)} questions → {QUIZ_PATH}")


def run() -> None:
    from pensine.mcp_server import recall  # import ici : charge la stack MCP
    if not QUIZ_PATH.exists():
        sys.exit("Pas de quiz — lancez d'abord `generate`.")
    quiz = json.loads(QUIZ_PATH.read_text(encoding="utf-8"))
    correct = 0
    with db.connection() as conn:
        for q in quiz:
            context = recall(q["question"])
            answer = llm.complete(ANSWER_PROMPT.format(
                owner=config.OWNER_NAME, question=q["question"], context=context))
            verdict = llm.extract_json(llm.complete(JUDGE_PROMPT.format(
                question=q["question"], expected=q["expected"], answer=answer)))
            score = 1.0 if verdict.get("correct") else 0.0
            correct += int(score)
            conn.execute(
                """
                INSERT INTO predictions (context, predicted, actual, error_score)
                VALUES (%s, %s, %s, %s)
                """,
                (f"fidelity:{q.get('domain', 'general')}", answer.strip(),
                 q["expected"], 1.0 - score),
            )
            flag = "✓" if verdict.get("correct") else \
                ("✗ HALLUCINATION" if verdict.get("hallucination") else "✗")
            print(f"{flag} [{q.get('domain')}] {q['question']}\n"
                  f"   attendu : {q['expected']}\n   jumeau  : {answer.strip()}")
        db.audit(conn, "mcp", "fidelity_run",
                 {"n": len(quiz), "correct": correct})
        conn.commit()
    print(f"\nScore : {correct}/{len(quiz)}"
          f" — seuil phase 2 : 9/10 sur les réponses factuelles.")


def report() -> None:
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT split_part(context, ':', 2) AS domaine,
                   count(*) AS essais,
                   round(avg(1 - error_score)::numeric, 2) AS score
            FROM predictions WHERE context LIKE 'fidelity:%%'
            GROUP BY 1 ORDER BY score
            """
        ).fetchall()
    if not rows:
        print("Aucun test passé encore.")
        return
    print(f"{'domaine':<20} {'essais':>6} {'score':>6}")
    for r in rows:
        print(f"{r['domaine']:<20} {r['essais']:>6} {r['score']:>6}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["generate", "run", "report"])
    p.add_argument("--n", type=int, default=10)
    args = p.parse_args()
    {"generate": lambda: generate(args.n), "run": run, "report": report}[args.command]()


if __name__ == "__main__":
    main()
