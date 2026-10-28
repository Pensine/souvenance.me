# Positioning: memory-integrity benchmark vs. existing benchmarks

Legend: ✓ covered as a primary measurement · ◐ partial/indirect · ✗ not covered · ? not verified.
† = metadata from search index only (re-verify). Cells reflect only what the cited page states; a "?"
means we could not check, not that the feature is absent.

| Benchmark | Write-time invention | Per-memory citation support | Recall/invention trade-off | Temporal staleness | Abstention | Multimodal life-log | Native ChatGPT/Claude tested |
|---|---|---|---|---|---|---|---|
| LoCoMo [maharana2024locomo] | ✗ | ✗ | ✗ | ◐ temporal questions | ? | ◐ images in dialogue | ? |
| LongMemEval [wu2025longmemeval] | ✗ | ✗ | ✗ | ✓ knowledge updates | ✓ | ✗ | ? |
| MemoryAgentBench [hu2026memoryagentbench] | ✗ | ✗ | ✗ | ✓ conflict resolution | ? | ✗ | ? |
| BEAM [tavakoli2025beam] | ✗ | ✗ | ✗ | ◐ contradiction resolution | ✓ | ✗ | ? |
| **HaluMem** [chen2025halumem] | ✓ extraction hallucination | ◐ vs. reference memory points, not a cited excerpt | ◐ integrity (recall) and accuracy (precision) reported separately | ✓ memory updating | ? | ✗ dialogue | ✗ not among listed systems |
| MemFail [garg2026memfail] | ◐ summarisation failures | ✗ | ✗ | ? | ? | ✗ | ? |
| FEB-30† | ◐ store inspected after each ingestion | ✗ | ✗ | ✓ fact evolution | ? | ◐ docs/emails/conversations (text) | ? |
| Ground Truth First† | ✗ | ◐ provenance-typed graph | ✗ | ✓ validity intervals | ? | ✗ | ? |
| Selective QA† | ✗ | ✗ | ◐ selective accuracy vs. coverage (answer time) | ✓ conflicting sources | ✓ | ? | ? |
| LifeBench† | ✗ | ✗ | ✗ | ? | ? | ◐ multi-source digital traces | ? |
| LifeDialBench† | ✗ | ✗ | ✗ | ◐ online protocol | ? | ✓ egocentric video / lifelog | ? |
| ReaLMem† | ✗ | ✗ | ✗ | ◐ attribute stability | ? | ✓ personal photo archives | ◐ API models, not native memory |
| Algorithmic Self-Portrait† (audit) | ◐ unilateral creation | ◐ grounding of entries in conversation | ✗ | ✗ | ✗ | ✗ | ✓ ChatGPT only |
| **Planned (Pensine)** | ✓ | ✓ excerpt verified in source | ✓ swept frontier | ✓ | ✓ | ✓ voice/notes/photos/docs | ✓ ChatGPT and Claude |

**Gap.** HaluMem measures write-time hallucination, but only against reference memory points in
dialogue. No benchmark in the set scores, *per stored memory*, whether a cited source excerpt exists and
supports it. None sweeps the write-time recall-vs-invention frontier. None combines that with multimodal
life-logs whose facts change over months. The only work touching native assistant memory is an audit of
ChatGPT†; we found nothing testing Claude's native memory. Claim: an *extension* of HaluMem along
per-memory support, trade-off curves, multimodality and native assistants. Not a first integrity
benchmark.
