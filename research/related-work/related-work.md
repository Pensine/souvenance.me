# Related Work

Citations in [brackets] are verified (see references.bib). Items marked † were found only through a
search index of their arXiv listing and must be re-checked before submission (see rejected.md §B).

**Memory architectures.** Long-term memory for LLM assistants is a crowded design space. MemGPT†
treats the context window as virtual memory, paged by the model itself. Mem0 [chhikara2025mem0] targets
production-scale extraction and retrieval. A-Mem [xu2025amem] organises notes after Zettelkasten
principles with model-generated links. MemoryOS [kang2025memoryos] borrows a tiered operating-system
analogy. HippoRAG [gutierrez2024hipporag] uses a hippocampal-indexing metaphor over a knowledge graph.
Several recent systems react against lossy extraction. MemMachine† calls itself
"ground-truth-preserving" and keeps whole episodes. Fidelity Before Structure† (first released as
CogCanvas†) reports that verbatim chunks beat extracted artifacts. Agent Zero Memory† attaches provenance
to every stored item. Pensine sits in this "keep the source" family. Its append-only event log with
memories as recomputable projections **(feature 1)** is the classical event-sourcing pattern and is
**not new**. Graphiti likewise retains invalidated facts instead of deleting them [graphiti2025repo], and
an event-sourced agent architecture (ESAA) is claimed in the literature, though we could not confirm its
identifier. Running on a 4B local model **(feature 10)** is an engineering property, not a research
contribution. Zero-LLM write paths already exist in open-source systems.

**Consolidation and forgetting.** Offline consolidation is well established. Generative Agents
[park2023generative] periodically synthesise reflections from observations. Letta's sleep-time compute
[lin2025sleeptime] moves work into idle periods. SCM† proposes NREM/REM-style consolidation with
value-based forgetting. OpenClaw's "Dreaming" runs light, REM and deep phases, and only the deep phase
promotes entries to durable memory [openclaw2026dreaming]. MemoryBank [zhong2023memorybank] introduced
Ebbinghaus-curve forgetting and reinforcement. HeLa-Mem† combines Hebbian co-activation edges with a
distillation step from an episodic graph to a semantic store. Pensine's sleep-inspired consolidation,
episodic→semantic gist promotion, forgetting curves **(feature 5)** and Hebbian links **(feature 6)** are
therefore **prior art**. The lab must not claim them. What we did not find in the verified or held set:
(a) persona amendments that are proposed by recombination but **never auto-ratified** and require the
user's signature in version control; (b) affect-weighted forgetting that treats **unknown valence as
distinct from neutral**. PsychoAgent (title only, unverified) describes affect-sensitive memory, so (b)
should be called *partially new* at most, pending a check of that paper.

**Temporal memory.** Bi-temporal knowledge graphs for agents are **prior art**: Graphiti/Zep advertises
"explicit bi-temporal tracking with automatic fact invalidation" [graphiti2025repo; Zep†]. Pensine's
PostgreSQL bi-temporal graph **(feature 3)** is an implementation choice, not a contribution. For temporal
reasoning, TReMu† summarises sessions with inferred dates and has the model write code for date
arithmetic. TSM† builds a semantic event timeline and merges continuous facts into durative memories.
Pensine's "lived time" **(feature 4)** computes humanised deltas and past/present/future status in code,
which overlaps with both. Using **personal landmarks and life chapters as temporal coordinates**, and
exposing *superseded-by-what-and-why* to the model, was not found. We rate feature 4 **partially new**.

**Attribution and hallucination in memory.** Attribution is mature for generation: RARR
[gao2022rarr] post-hoc researches and revises outputs, ALCE [gao2023alce] benchmarks generation with
citations, FActScore [min2023factscore] scores atomic factual precision, and AttributionBench
[li2024attributionbench] shows that automatic attribution judgments are hard. Inside memory systems,
HaluMem [chen2025halumem] is the decisive precedent. It describes itself as the first *operation-level*
hallucination benchmark for memory systems and scores memory extraction (integrity = recall of reference
memory points; accuracy = precision), memory updating (accuracy, hallucination, omission) and QA.
MemFail [garg2026memfail] decomposes systems into summarisation, storage and retrieval and stress-tests
each. ProMem† adds self-questioning during extraction to recover and correct facts. A recent survey
frames evidence tracing and execution provenance for agents [wang2026tracesurvey]. Against this
background, Pensine's write-time admission cascade **(feature 2)** combines a **code-verified verbatim
excerpt**, lexical checks on numbers and proper nouns against the source, and an LLM review only for
flagged items. It is **partially new**: the individual ideas (attribution, atomic checking, provenance)
are prior art, but we found no system that gates *admission* on a mechanically verified quote and
reports an invention rate at write time. The fidelity harness **(feature 9)**, a blind self-quiz per
life domain, resembles HaluMem's QA stage and ProMem's† self-probing, so it is also only **partially
new**.

**Memory benchmarks.** LoCoMo [maharana2024locomo] and LongMemEval [wu2025longmemeval] established
long-horizon conversational memory evaluation. LongMemEval explicitly tests knowledge updates, temporal
reasoning and abstention. MemoryAgentBench [hu2026memoryagentbench] adds test-time learning, long-range
understanding and conflict resolution. BEAM [tavakoli2025beam] scales to 10M-token conversations and
includes abstention and contradiction resolution. A 2026 wave argues that end-to-end QA hides memory
defects. FEB-30† inspects the memory store after each ingestion step over 30 fact-evolution
trajectories. Ground Truth First† generates facts with validity intervals before rendering text and
shows that rankings change with history length. Selective QA† measures abstention over conflicting
personal sources. Our planned benchmark is an **extension of HaluMem** in this line, not a first.

**Personal and life-log memory.** Second Me† proposes a personal "AI-native memory". TwinVoice
[du2025twinvoice] evaluates persona simulation, including memory recall. LifeBench† targets
non-declarative memory inferred from multi-source digital traces. LifeDialBench† evaluates continuous
lifelog memory from egocentric video and simulated communities, under an online protocol. ReaLMem†
uses multi-year multimodal personal photo archives. Closest to our concern with *native* assistants,
The Algorithmic Self-Portrait† audits real ChatGPT memory entries and reports that most were created by
the system without user initiation. That finding motivates Pensine's consent flow with rejection of
too-fast confirmation **(feature 7)**. Proposal-with-consent exists in products. We did not find the
"too-fast confirmation" rejection rule in the literature, so it is a **minor, possibly new** design
detail and not a research claim.

**Security of memory.** Poisoning and injection attacks on agent memory are documented. AgentPoison
[chen2024agentpoison] poisons memory or knowledge bases with triggers. MINJA† injects malicious records
through queries alone. A-MemGuard† defends with consensus checks across memories. Spotlighting†
marks untrusted input provenance in prompts. Screening stored content for prompt injection
**(feature 8)** is **prior art** and good practice, not a contribution.

**Summary of originality claims.** Not new: features 1, 3, 5 (consolidation, forgetting curves), 6, 8,
10. Partially new: 2 (verbatim-gated admission with measured invention rate), 4 (landmark/chapter
coordinates), 5-subparts (signed, never auto-ratified persona amendments; unknown-≠-neutral affect),
9. Minor/possibly new: 7. The defensible research contribution is the **measurement**: per-memory
support of the cited excerpt and the write-time recall-vs-invention frontier on multimodal synthetic
life-logs, positioned as an extension of HaluMem.
