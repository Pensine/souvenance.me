# External benchmarks: can we run them? (2026-11-03)

Web check only; figures read in the papers unless marked "inferred".

## StateMemBench (arXiv 2608.19652, v1, 20 Aug 2026)
- Measures whether a memory answers from the current state or a superseded
  one ("drift"), plus anti-trap probes where the right move is not to update.
  Synthetic: symbolic event programs, deterministic gold, dialogue written by
  Sonnet 4.6. 234 scenarios, 322 graded probes (Set A: 190 x 18 sessions,
  ~3k tokens; Set B: 44 x ~38 sessions, 7-15k tokens).
- Scoring: closed pool (gold, drift, distractors); word-boundary matcher,
  else an LLM judge fixed to deepseek-v4-pro.
- Reported gold rates are low for everyone (Mem0 .15-.18, full context .15,
  the authors' StateMem .23-.36); Zep/Graphiti and Letta not evaluated.
- Ingestion ~1M tokens in all (inferred: ~50x less than LongMemEval_S).
- **Blocker: no public data or code found, no license stated.** Next step:
  write to the authors.
- Authors' limits: synthetic, short contexts, single runs, judge shares a
  family with one answering model.

## HaluMem (arXiv 2511.03506)
- Public: github.com/MemTensor/HaluMem, huggingface.co/datasets/IAAR-Shanghai/HaluMem.
- License CC-BY-NC-ND-4.0 (evaluation fine, no redistribution of modified data).
- 20 users per version, 14,948 memory points, 3,467 QA pairs; Medium
  ~160k tokens per user (~3.2M in all), Long ~1M per user.
- Judge model not checked yet (eval/README.md).
