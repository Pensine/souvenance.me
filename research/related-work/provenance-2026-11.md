# Prior art: source-checked memory writes (checked 2026-11-03)

What Pensine does: no fact, no subject and no identity link (role <-> name)
is written without an excerpt that code finds in the source deposit.

## Already done by others (credit them)

- **SodaMem** (arXiv 2608.08055, Aug 2026), "Evidence-Grounded Temporal Graph
  Memory": provenance spans that must occur literally in the source turn,
  invalid candidates rejected; mention / occurrence / validity times.
  https://arxiv.org/abs/2608.08055
- **Eywa** (arXiv 2605.30771, May 2026), "evidence before belief": raw
  evidence stored first, extracted memories validated against source overlap
  and hard values (dates, amounts), validity windows.
  https://arxiv.org/abs/2605.30771
- **MemIR** (arXiv 2605.25869): verbatim evidence spans cited by claims
  (copying asked in the prompt; no code check described).
- **TierMem** (arXiv 2602.17913): findings linked to raw sources.
- **Zep / Graphiti**: per-edge provenance to whole episodes, bi-temporal
  validity; no excerpt per fact (Zep: string matching cannot recover the source
  once the LLM rewrites it).
  https://www.getzep.com/blog/how-zep-tracks-provenance-in-agent-memory/
- Answer-side quote checking: ALCE (arXiv 2305.14627), Anthropic Citations API.

## Benchmarks measuring the same failures

- HaluMem (arXiv 2511.03506; accepted at EMNLP 2026 per its authors'
  repository): hallucination at extraction, update and QA.
- Memora, "From Recall to Forgetting" (Findings of ACL 2026,
  2026.findings-acl.1337): reuse of stale memories (FAMA).
- LongMemEval (ICLR 2025): recall, updates, temporal reasoning.

## What we may claim

- The same write gate applied to identity links (no role <-> name link without
  a verified excerpt): not found in the systems and papers above; a gap in
  what we found, not proof of absence.
- The measurements: sealed sets written blind, same model and embedder for
  every system.

## What we must not claim

- First to verify source excerpts before writing a memory (SodaMem, Eywa).
- First bi-temporal memory or per-fact provenance (Zep / Graphiti).
- "The model reads, the code proves" is a principle we apply, not an invention.
