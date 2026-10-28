# Founding interview — 3 to 4 sessions (phase 0)

Audio preferably (commuting, walking). Each session: 30 to 45 minutes, in the
"Pensine" assistant project. The transcript of each session is ingested as the
first events (`scripts/ingest_interview.py`). After that the interview
dissolves into everyday use: the system fills its gaps by slipping a question
into natural conversations, never as an interrogation.

Instruction to give the assistant at the start of a session: *"You are running
founding interview session no. X (theme below). One question at a time,
follow up on concrete details and lived examples, never judge, and only
summarise at the end."*

## Session 1 — Biography and chapters
- The chapters of your life, as you would divide them yourself (titles, turning points).
- The 3 or 4 events that shaped you most — and what they changed.
- The places that matter (and why those ones).
- What you keep from your childhood; what you chose to leave behind.

## Session 2 — Values, spirituality, contradictions
- What you do not negotiate on. What you have already betrayed, and what it taught you.
- The place of the spiritual, or of meaning, if it exists for you: practices,
  doubts, what "making the most of what was entrusted to you" means
  in concrete terms.
- Two tensions you accept (e.g. ambition ↔ discretion, elsewhere ↔ home) —
  name them without resolving them.
- What reliably makes you angry. What restores you.

## Session 3 — Decision style and work
- Three important recent decisions: how they were really
  made (not the tidy version — the actual sequence).
- What you do when you hesitate. Your relationship to risk, to money,
  to time.
- How you work well: conditions, hours, formats. What drains you.
- Your writing style: three texts of yours that you think ring true.

## Session 4 — Relationships, projects, fears, horizon
- The people who matter: what each relationship gives you and asks of you.
  *(Third-party rule: we talk about your relationship to them, not about what they confided.)*
- Current and dreamed-of projects — and which ones are real.
- The fears that operate (the ones that influence decisions).
- In 10 years: what should this system be able to remind you of
  from today?

## Ingestion

```bash
./.venv/bin/python scripts/ingest_interview.py --session 1 --date 2026-08-10 transcript_s1.txt
```
