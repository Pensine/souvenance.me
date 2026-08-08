# 001 — The substrate thesis

**Working title:** *Own the substrate: why a personal memory system stays
relevant across AI generations — because it presupposes their obsolescence.*

**Type:** position paper (argument, not measurement — stated as such in the
abstract).
**Status:** **draft v0.2** — see [`paper.md`](paper.md). Two literature sweeps
have landed and been filtered; thirteen sources survived verification out of
roughly twice that number returned. Open work is listed below.
**Target:** Zenodo preprint with DOI, linked from the repository README.

---

## The claim in one paragraph

Personal AI memory is being built the wrong way round. Systems are coupled to
the model generation that exists when they are written, so each leap in
capability threatens to obsolete them. We argue for the inverse architecture:
an append-only event log owned by the subject, from which every intelligent
layer is a *recomputable projection*. Under this design, progress in AI is not
a threat but an input — a better engine re-reads the same life and produces a
better memory of it. We show that the properties which survive across model
generations are not capabilities (which commoditise) but **provenance,
governance and portability** (which do not), and we argue that no lab has an
incentive to provide them.

## Skeleton

### 1. Introduction — the asymmetry
Models improve; lived experience does not regenerate. As frontier capability
commoditises, scarcity migrates from processing to corpus. State the paradox
the paper resolves: *why build now, if tomorrow's AI will be far better?*

### 2. Background `[TO WRITE — needs the sweep]`
- Memory in LLM products: what is actually stored, and by whom
- Memory layers for developers (Mem0, Zep/Graphiti, Letta): components, not
  possessions
- Personal knowledge management and the lifelogging lineage (MyLifeBits,
  Memex) — why previous attempts died: capture cost, not storage cost
- **World models** (LeCun's programme, JEPA, LeWM): the incumbent architecture
  is expected to be superseded *by its own critics* → see
  [`../../notes/world-models-jepa.md`](../../notes/world-models-jepa.md)

### 3. The substrate thesis
- **3.1** Event sourcing as the invariant: memories are projections, not
  records. Re-consolidation as migration.
- **3.2** What survives a model generation: provenance, calibrated confidence,
  validity intervals, originals. What does not: extraction quality, embedding
  space, prompt design — and why it is correct that these are disposable.
- **3.3** The adapter argument: the AI layer as a plug. Capture must never
  depend on the intelligent layer (pause, never loss).
- **3.4** Lived time as a durable primitive: models have no internal clock;
  framing computed in code is model-independent by construction.

### 4. What the labs will not do
Incentive analysis rather than capability analysis. Accumulated context is the
moat; portable memory works against the holder's interest. Cite the 2026 study
on unilateral memory creation. Distinguish clearly: *they could, they will not.*

### 5. Threat model — the honest section
The section that decides whether the paper is credible.
- **T1. Context ceases to be scarce.** Hundred-million-token windows make
  consolidation unnecessary: feed everything raw. → The intelligent layer dies,
  the substrate survives. Concede this fully; it strengthens the architecture.
- **T2. Labs ship portable, interoperable memory.** → Portability argument
  weakens; ownership and governance arguments do not.
- **T3. Capture never becomes effortless enough.** The historical killer of
  lifelogging. → The real risk, and it is behavioural, not technical.
- **T4. The corpus proves less valuable than assumed.** n=1, ten-year horizon,
  unfalsifiable in the short run. → State it plainly.

### 6. Souvenance as an instantiation
Brief. The paper argues an architecture; the implementation is evidence that
it runs, not the subject.

### 7. What would falsify this
Commit to it: if within N years a major provider offers exportable,
interoperable, auditable memory with user-held governance, the portability
argument is void. Name the test before knowing the answer.

### 8. AI use disclosure
Drafting, literature synthesis and adversarial critique were assisted by large
language models. All claims, experiments, conclusions and errors are the
author's.

---

## Open work on the draft

| # | What | Why it matters |
|---|---|---|
| 1 | Re-projection cost at decade scale is **unmeasured** | Objection 5.1's surviving residue and falsification test #2. SIM answers the architecture question but its search unit filters against a *candidate item*; open-ended personal queries have no such filter. Measurable on synthetic corpora. |
| 2 | Paper 002 (temporal ablation) is the measured companion | Falsification test #4 depends on it. A position paper alone stays an argument. |
| 3 | SenseCam clinical recall figures unverified | If the reported gains from passive visual capture on episodic recall hold up, they are direct evidence that a substrate aids genuine reconsolidation. Currently **not cited** — the specific percentages were not traced to the primary papers. |
| 4 | Digital legacy section cut for scope | Öhman & Floridi, Hollanek & Nowaczyk-Basińska, Spanish LO 3/2018 Art. 3 look real and relevant. Verify before writing the section. The third-party consent problem in mixed archives is genuinely unsolved and worth a paper of its own. |
| 5 | Capture-friction retention is the live risk | §5.4 concedes it with numbers. Falsification test #5 — the one we expect to be tested first, and it is measured by usage, not by literature. |

## Brief for the literature sweep

Kept for reproducibility — this is what produced the current draft. Round two
should be narrow (rows 1 and 3 above), not another broad pass.

Ask for **sources with links and dates**, and for contradicting evidence — a
sweep that only confirms is useless. Note from round one: the tool returned
several plausible-looking citations that did not survive verification, and one
self-contradictory benchmark table. Verify every figure before it enters a
draft.

> I am writing a position paper arguing that a personal AI memory system
> should be built on an append-only, user-owned event log, with the AI layer
> treated as a replaceable adapter, so that the system benefits from — rather
> than being obsoleted by — future AI progress. For each point: primary
> sources, dates, and where the claim is contested.
>
> 1. **State of memory in AI products (2024–2026).** What ChatGPT, Claude,
>    Gemini and Copilot actually persist about a user. Is any of it exportable
>    in reusable form? Any interoperability standard emerging? Quantified
>    studies on how memories are created (user-initiated vs system-initiated)
>    and what they infer.
> 2. **Developer memory layers.** Mem0, Zep/Graphiti, Letta/MemGPT: architecture,
>    benchmark results (LoCoMo and its critiques), what they explicitly do not
>    cover. Independent evaluations, not vendor claims.
> 3. **World models and the post-LLM debate.** LeCun's position (JEPA, V-JEPA,
>    LeWM 2026), the strongest counter-arguments, and the state of scaling-law
>    debates on autoregressive limits. Who predicts what, and on what evidence.
> 4. **Memory consolidation in neuroscience.** Systems consolidation, sleep and
>    REM replay, active forgetting, reconsolidation of recalled memories,
>    memory as reconstruction. Recent reviews. Also: where the brain analogy is
>    considered misleading in ML.
> 5. **Temporal cognition.** Tulving's chronesthesia and mental time travel;
>    prospective memory; documented failures of LLMs on temporal reasoning
>    (benchmarks, error taxonomies); bi-temporal modelling in databases.
> 6. **Lifelogging, history and failure modes.** Memex, MyLifeBits, Sony
>    LifeLog, Rewind/Limitless, Humane. Why did they fail — capture friction,
>    privacy, value? Evidence, not narrative.
> 7. **Data ownership, portability and law.** GDPR Art. 20 and its practical
>    limits for derived profiles; the EU Data Act; whether a distilled model of
>    a user counts as personal data.
> 8. **Digital legacy and posthumous data.** Griefbots, consent after death,
>    academic ethics literature. Existing frameworks for testamentary clauses
>    over personal archives.
> 9. **Compounding value of personal data.** Any empirical work on how the
>    utility of a personal corpus evolves with time and volume. Also the
>    counter-case: evidence that recency dominates and old context decays.

## Files

- [`paper.md`](paper.md) — the manuscript, draft v0.1
- [`references.bib`](references.bib) — verified sources, plus an explicit
  rejected-sources block so the filtering is auditable
