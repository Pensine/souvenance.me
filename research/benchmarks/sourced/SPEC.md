# SOURCED — specification v0.1 (draft)

**SOURCED: a benchmark of memory integrity over a synthetic life.**
(Name checked 2026-10-28: no benchmark, dataset or method of that name on
arXiv, Hugging Face or GitHub. Adjacent: "SourcedRecall", a local AI-memory
product on Hugging Face. The PyPI name `sourced` is taken by an unrelated
code-analysis tool, so any package would be `sourced-bench`.)
Does a personal memory system write only what the person's own deposits
support, can every memory show the excerpt it comes from, and does it stay
right while the facts of a life change over months?

Status: protocol draft and working generator. **No system has been measured
yet**. The only numbers in this folder come from control systems and from a
scripted run of one adapter on a 2-week toy sample. They validate the
harness. They are not results (see `results/README.md`).

---

## 1. Why another benchmark

Most memory benchmarks score answers to questions about long chat logs. They
check the end of the pipe. A personal memory has a different failure mode,
one that answer accuracy hides: **it writes things the person never said**,
and from then on it repeats them as facts. An omission can be fixed later
from the raw deposit. An invention keeps doing harm.

SOURCED measures the store itself, at write time, against a truth that was
generated *before* the deposits. It does this on the material a life actually
leaves behind: voice memos, notes, messages, dated and geotagged photos,
documents.

## 2. Prior work and position

SOURCED **extends** existing work. It is not the first benchmark of
memory hallucination, nor the first "truth-first" generator. All references
below were checked against their primary pages on 2026-10-28 (arXiv abstract
and HTML pages, ACL Anthology, repositories).

| Work | What it already does | What SOURCED adds |
|---|---|---|
| **HaluMem** (Chen et al., arXiv 2511.03506) | Hallucination at the operation level: memory extraction, updating, QA. Synthetic user–AI chat. Evaluates Mem0, Memobase, MemOS, Supermemory, Zep. Data CC BY-NC-ND 4.0 | Excerpt support per memory, non-chat multimodal deposits, open license |
| **Ground Truth First** (Spencer, arXiv 2607.21962) | Fact script written first. Write-stage audit of every stored memory (correct / distorted / absent; hallucination / distortion / misattribution). Validity intervals, as-of questions, abstention. Chat + email text. Corpus CC BY 4.0 | Cited-excerpt check, voice / photo / document deposits, photo-content traps, a recall/invention curve |
| **FEB-30** (Toma et al., arXiv 2610.22209, AWS) | Inspects the memory store after each ingestion of generated documents, emails and chats. Fact-evolution trajectories, create / update / supersede operations | Scores invention and excerpt support directly. Multimodal personal deposits. (FEB-30's linked repository returned 404 on 2026-10-28) |
| **Selective QA over Conflicting Multi-Source Personal Memory** (Yang et al., arXiv 2605.30087) | Answer or abstain over 5 synthetic, conflicting personal text streams | Write-time integrity. Abstention mandatory inside one headline score |
| **LongMemEval** (Wu et al., arXiv 2410.10813, ICLR 2025) | 5 abilities over chat histories, including knowledge updates and abstention | Store-level audit, non-chat deposits |
| **LoCoMo** (Maharana et al., arXiv 2402.17753, ACL 2024) | Very long multi-session dialogues. QA with an adversarial (unanswerable) category. Images shared as URLs + captions. CC BY-NC 4.0 (repo LICENSE.txt; the arXiv page says BY-NC-SA) | See §4.4: abstention cannot be excluded from the headline |
| **ALCE** (Gao et al., arXiv 2305.14627, EMNLP 2023) | Citation quality of *generated answers* | The same idea applied to *stored memories* |
| **FActScore** (Min et al., arXiv 2305.14251, EMNLP 2023) | Atomic-fact precision against a knowledge source | Atomic support against the person's own deposits |
| MemoryAgentBench (Hu et al., arXiv 2507.05257), BEAM (Tavakoli et al., arXiv 2510.27246), RealMem (Bian et al., arXiv 2601.06966), LifeDialBench (Zheng et al., arXiv 2604.11182), LifeBench (Cheng et al., arXiv 2603.03781) | Long-horizon, project, lifelog or multi-source memory, scored on downstream answers | Write-time integrity and excerpt support (none of these score them, as far as their abstracts state) |

**Identity and attribution.** Three recent benchmarks score who a memory is
about. SocialMemBench (Owolabi, arXiv 2605.17789) works on group chats, with
entity merging and attribution. GroupMemBench (Yang, arXiv 2605.14498) asks
asker-specific questions over per-speaker beliefs. SpeakerMem-R1 (Zheng,
arXiv 2609.26780) trains speaker-aware memory with a reward against
attribution errors. Ground Truth First (above) already labels
"misattribution" in its write-stage audit. None of them works on a
single-owner life-log, where the owner names other people by role ("my
sister") as often as by name, and none stores the identity decision itself.
Graphiti (open-source code, `dedupe_nodes.py`) merges entities by asking an
LLM whether a candidate is a duplicate; it keeps no excerpt, no confidence
and no way to undo the merge. SOURCED adds (a) an attribution error rate
measured on its own over stored memories that declare a subject (§4.1), and
(b) questions that can only be answered by resolving a role to a name
through a deposit that proves the alias (§4.3). The companion engine change
in Pensine stores each alias decision as a claim with its quoted excerpt and
a confidence, which can be retracted (`pensine/identity.py`). A claim is
admitted only when its excerpt joins the alias and the name in one clause
by an identity form ("my sister Priya", "Priya, my sister", "Priya (my
sister)", "Priya is my sister"); two names that only share a sentence
("Told Oskar that my sister works at …") are refused. Identities never
written that way are covered by a second, separate tier: an *inferred*
claim, built in code from at least two specific attributes the role and
the name share in different deposits (each support quote-checked), used in
recall only with a hedge and never to attach facts, promoted by a later
identity form or the owner's confirmation, refuted by the two appearing
together in one deposit. SOURCED scores both tiers (§4.1, alias recall and
precision). We do not
claim the first attribution or speaker benchmark.

**Bounded dating.** Temporal reasoning benchmarks give the dates and test
relations between them: ChronoSense (Islakoglu, arXiv 2501.03040) scores
Allen relations over given event dates. When Silence Is Golden (Zhou, arXiv
2602.04755) scores temporal abstention, all or nothing. Temporal Semantic
Memory (Su, arXiv 2601.07468) stores event time in agent memory, as points,
without uncertain bounds. Agent Zero Memory (Wu, arXiv 2608.29606) keeps
evidence pointers and abstains. SOURCED adds facts whose date no deposit
states, only brackets ("not yet" one day, "already" a later one), questions
whose gold is that interval, and an **invented precision rate**: answering
one exact date where the evidence supports only an interval. Abstaining is
reported apart. The companion change in Pensine stores each event-time bound
with its own quote and derives intervals in code (`pensine/dating.py`). We
do not claim the first temporal-interval benchmark or the first temporal
abstention metric.

**The gap.** No benchmark we found combines (a) invention measured at write
time, (b) a check that *each stored memory* is supported by the excerpt it
cites, and (c) heterogeneous personal deposits (voice, photos, documents)
whose facts change over months. Closest on (a): Ground Truth First and
HaluMem. Closest on change over time: FEB-30 and Ground Truth First. On (b),
only ALCE, and only for answers. On (c), nothing truly multimodal: LoCoMo has
images inside dialogue, and part of LifeDialBench comes from egocentric video.

## 3. The data

### 3.1 Truth first

`sourced/world.py` builds a `World` from a seed and four parameters: start
date, days, target facts, target changes. Default release: 182 days,
300 facts, 40 changes. The world holds:

- **people**: the owner and ~50 relatives, friends and colleagues
  (fictional names). Each has a relation to the owner and a role phrase,
  the way the owner designates them without a name ("my sister");
- **facts**: atomic statements with `valid_from` / `valid_to` (exclusive,
  `null` = still true). There are *state* facts (lives at, works at, pays
  rent, dating, project stage, commute, hobby, gym, pet, allergy, …) and
  *event* facts (visited a place, met someone, ran a race, appointment,
  someone else's news). A *change* is a new version of a slot (`supersedes`
  links the versions), or a state that begins inside the window (illness
  onset, start of a relationship). Health facts are benign only;
- **traps**: sentences that must not become memories as stated. Each trap
  stores the false claim a careless writer would make:
  - `hypothetical` ("If the Valencia offer comes through, I'd move");
  - `plan` ("thinking about adopting a dog");
  - `negation` ("in the end I did not sign up");
  - `hearsay` ("X said their bike got stolen" → "the owner's bike was
    stolen", or a rumour stated as done);
  - `photo_content`: every photo is a neutral, non-figurative image
    (§3.3), so any description of what it "shows" is an invention;
  - `attribution`: the owner reports a true fact about someone else ("my
    sister works at Marrowgate Press"), and the careless version stores it
    about the owner, or about the other person named in the same sentence
    ("Told Oskar that my sister works at …" → "Oskar works at …"). The
    people a careless writer would pick are listed in `misattributed_to`.
    Hearsay is about a *reported claim* (it was only said); attribution is
    about the *subject* (the fact is true, of someone else).
- **identity layer**: a few people (2 on the 2-week sample, 5 on the
  release) get two extra facts, an employer and a choir they join. The
  employer is deposited by **role only**, the choir by **name only**, and
  one earlier deposit names role and name **together** ("Dinner with my
  sister Priya tonight"): the only place the alias is provable (its span is
  in `meta.alias_spans`). A role phrase designates one person: a relation
  the life holds twice is qualified ("my colleague from the book group").
  The layer draws on its own random streams, so the base life, its
  deposits and their ids are byte-identical with or without it (tested;
  `generate_world(identity=False)` turns it off). Its facts carry
  `layer: "identity"` and are added on top of the fact target;
- **coverage layer**: four role/name pairs, on new people with relations
  no one else holds, never written together. *converging*: one person,
  named by role in two notes and by name in two others, sharing a city and
  an employer (an identity the evidence supports, but only by inference);
  three decoys, two people each: *one_attribute* (same city, different
  employers), *generic* (same city, and "works from home"), *together*
  (same city and employer, but a later note has "lunch with my landlady and
  Pablo"). Truth in `coverage`, text notes only, numbered after the dating
  layer, own random streams (`generate_world(coverage=False)`); earlier
  deposits, recipients included, are byte-identical (tested);
- **dating layer**: a few facts (2 on the 2-week sample, 8 on the release)
  whose date is only bracketed: someone waits for a thing (day A: "the
  kayak I ordered has not arrived yet"), then has it (day B: "Oskar already
  has the kayak"). The true day lies in [A + 1, B] and is written in no
  deposit; all the evidence supports is [A, B] (inclusive, day precision).
  The "not yet" span has role `not_yet` and does not count as stating the
  fact (`tasks.asserted`), the "already" span role `already`. Text deposits
  only, numbered after the identity layer, on their own random streams
  (`generate_world(dating=False)` turns it off; tested byte-identical);
- **unstated slots**: questions no deposit can answer.

Real cities supply real GPS coordinates. Every organisation, street and
person is fictional. No document imitates a real organisation.

### 3.2 Deposits

`sourced/deposits.py` writes each deposit *from* the facts, and records the
exact character span of every fact it carries (`spans`, role `mention`,
`start`, `end`, or `future` for announced facts such as an offer letter
dated before the start date). It also records which traps it contains.
Kinds:

| Kind | Author | Track T text | Track R file |
|---|---|---|---|
| `note` | owner | the note | `.txt` |
| `message` | owner → someone | the message | `.txt` |
| `message_in` | someone → owner | the message (their facts in the first person) | `.txt` |
| `voice` | owner | reference transcript, with hesitations and restarts | `.m4a` (Chatterbox TTS + noise) |
| `voice_in` | someone → owner | reference transcript | `.m4a`, another voice |
| `photo` | owner | `Photo taken on <date> at <time>. GPS: <lat>, <lon>.` | `.jpg` with EXIF DateTimeOriginal + GPS |
| `document` | — | lease, offer letter, visit summary, finisher certificate | `.pdf` |

Identity-layer deposits are notes and messages, never voice, and are
numbered after the base deposits (the list stays in time order), so the ids
of base deposits and the media files named after them do not move.

Relative dates ("today", "yesterday") are used on purpose: turning them into
dates is part of the task. The same fact is often stated more than once,
in different deposits and wordings, so systems are tested on deduplication.

### 3.3 Media

- **Photos**: seeded colour fields and shapes, never figurative, never
  presented as a real event. EXIF carries date, time and GPS
  (round trip tested).
- **Voice**: Chatterbox (`chatterbox-tts` 0.1.7, Resemble AI, MIT) run
  locally, cloning five voices zero-shot from ~10 s public-domain LibriVox
  clips (§9, `sourced/voices/refs/REFS.md`). The world draws one of five
  engine-neutral slots per speaker (`female_a`, `female_b`, `male_a`,
  `male_b`, `female_gb`); the owner has a slot of their own and the partner
  and friends share the other four. Every file carries Resemble's
  imperceptible Perth watermark, which marks it as synthetic; the worker
  refuses to write audio if the watermarker is unavailable. Piper (§9) is
  kept as a fallback engine on the same slots. Hesitations and restarts are
  in the transcripts; the worker adds light noise (~-38 dBFS) and a random
  lead-in. Generation is seeded per deposit (§10).
- **Documents**: a minimal PDF writer (no dependency). The text is
  extractable (checked with an independent parser).

### 3.4 Tracks

- **Track T (text)**: systems receive the reference text of every deposit.
  This isolates memory writing from speech recognition and OCR errors. It
  is the main track.
- **Track R (raw)**: systems receive only files. This measures the full
  pipeline. Same truth, same scoring.

## 4. Metrics

All rates are reported with their denominators. Nothing is imputed: a metric
a system cannot be measured on is `null` with a reason. A missing citation
is a failure of excerpt support, not a missing value.

### 4.1 Write-time integrity (store snapshot, weekly and at the end)

For each memory *m* in the snapshot, the judge (§6) returns:

- `support` ∈ {supported, partial, unsupported}: do the person's deposits
  entail *m*? Ordinary world knowledge is allowed (the city a GPS position
  falls in, the full names of known people). A trap stated as an
  accomplished fact is unsupported. So is any visual description of a photo,
  or someone else's fact attributed to the owner;
- `facts`: the gold facts *m* states, each marked `correct` or `wrong_value`;
- `citation_found` (code): at least one cited excerpt occurs in the cited
  deposit. Exact match after normalisation, or ≥ 90 % word-window similarity
  (tolerates hesitations);
- `citation_supports` (judge): the cited excerpts alone entail *m*.

Metrics:

| Metric | Definition |
|---|---|
| **Invention rate** | unsupported memories / all memories |
| Partial rate | partial / all |
| **Excerpt support rate** | memories with `citation_found` ∧ `citation_supports` / **all** memories |
| **Fact recall** | gold facts deposited before the snapshot that are stated correctly by ≥ 1 memory / those gold facts |
| Omission rate | 1 − fact recall, also by kind (state, event, change) |
| Trap hits | traps whose false claim appears in the store |
| **Alias recall** | true identities (identity-layer persons whose alias deposit precedes the snapshot, coverage *converging* persons whose four deposits do) linked by the system / true identities; also by kind and by the tier of the link. `null` with a reason if the system exposes no links (`MemorySystem.aliases()`) |
| **Alias precision** | links whose alias and name designate the same person / all links; false links listed |
| Store invented precision | among bracketed gold facts whose memories expose event bounds (`MemoryRecord.event_earliest` / `event_latest`), the share exposed as one exact date. `null` with a reason if the system exposes no bounds |
| Stale-as-current | superseded gold facts that a memory still marks as current / superseded facts. `null` if the system does not expose currency |
| **Attribution error rate** | among memories that state the value of a gold fact *and* declare a `subject`, the share whose subject is not that fact's subject. `null` with a reason if the system declares no subject (never 0) |

**Attribution, in code.** A memory may declare whom it is about
(`MemoryRecord.subject`: a name or a role phrase). The judge maps it to a
person (full name, first name, or a role phrase that designates one
person), finds the gold facts whose *value* the memory states regardless of
who it names, and counts the memory as misattributed when the declared
person is the subject of none of them. Matching by value is lenient: a
wrong subject that happens to be the subject of another fact with the same
value (two people in Porto) is accepted, so the rate is a lower bound. The
model judge keeps this check in code.

### 4.2 The recall/invention curve

If a system attaches a confidence to its memories, we sort the store from
most to least confident. At each threshold we record (invention rate among
kept memories, fact recall). Headline points: **recall at invention ≤ 1 %**
and **≤ 5 %**. A system without confidence gets a single point.

This answers the question a user actually faces: *how much of my life can
this memory hold before it starts making things up?*

### 4.3 Question answering

Questions are asked "now" (the day after the window). They are derived
from the truth only, and one question text always has one answer (ambiguous
duplicates are dropped by construction). Categories:

| Category | Example | Gold |
|---|---|---|
| present | Which company does Maya work for now? | current version |
| past | In which city did Maya live on 12 March 2025? | version valid that day |
| when | When did Maya start working at Oakline Software? | ISO date, exact |
| duration | How many days did Maya's ear infection last? | integer days, ±1 |
| event | What was Maya's finishing time at the Spring 10K on …? | value |
| attribution | Who moved to Porto on …? | the other person |
| abstention | What is the name of Maya's dog? (she only *thought* of adopting one) | must abstain |
| identity | Which company does Priya work for now? (deposited as "my sister works at …") · Which choir did Kofi's sister join? (deposited as "Priya joined …") | the target's value; the alias deposit is listed in the evidence |
| attribution_check | Which company employs Kofi now? · Which choir did Kofi join? · Which company does Oskar work for now? | the true subject's value, or abstain; the misattributed value is recorded as a `distractor` |
| bounded_date | When did Oskar get the standing desk? | the interval "A/B" the deposits support (answer type `interval`) |

`attribution` asks *who* did something; `identity` and
`attribution_check` come from the identity layer and are numbered after
the other questions, so the ids of those do not move.

**Bounded dates, in code.** The answer's dates are parsed (a day written
without its year borrows the next year written). Two or more dates: the
answer is **correct** if its interval lies within the gold interval or
equals it, with `tolerance_days` on each side (0 in this release). One
date: **invented precision**, even when that date is inside the interval.
An abstention is counted apart (`bounded_date.abstained`); it is not
correct, and not an invention. Anything else (a wider interval, no date) is
wrong. **Invented precision rate** = invented-precision answers / all
bounded_date questions.

Answer matching is done in code: dates parsed from the answer, numbers
(digits or words), normalised string containment for names. A hedged
answer ("I don't know, maybe Porto") counts as an abstention.

### 4.4 Abstention is mandatory (lesson from LoCoMo)

LoCoMo's adversarial category is often left out of reported scores, which
lets a system that never abstains look better than it is. In SOURCED:

- abstention questions are about 20 % of the set and are drawn from traps,
  unstated slots and photo-content questions;
- the headline **QA accuracy** is computed over *all* questions. No option
  removes a category. A system that always abstains scores exactly the
  abstention share (tested);
- we also report **invented answers** (abstention questions answered),
  answered precision and coverage.

### 4.5 Headline

Each system is reported as one row, with no aggregate index:
**invention rate · excerpt support rate · fact recall · recall at
invention ≤ 1 % · attribution error rate · alias recall / precision · QA accuracy (abstention
included) · invented answers · invented precision rate**.

## 5. Protocol

1. `generate` with the release seed. Check `manifest.json` (SHA-256 of
   the truth and of every file).
2. `run`: the harness feeds each system one day of deposits at a time,
   calls `end_of_day`, and takes a snapshot of the store every 7 days
   and at the end. Then it asks every question once. Systems never see
   labels. `DepositView` has only id, kind, timestamp, author, recipient,
   text or path (tested).
3. `score` with the frozen judge. Publish the run file, the report and the
   judge identity (model, quantisation, prompt hash).

**Fairness rules.** Each system runs with its documented defaults. When a
system has no answer generator of its own, all systems use the **same
open-weights reader** (pinned) over their retrieved context, so retrieval is
what gets compared. Timestamps are passed wherever the API accepts them, and
a clock the system does not let us set is reported, not corrected. One run
per system per seed. Five seeds for the release, with reported variance.

## 6. Judge

- **Code first**: citation existence, date and number matching, answer
  matching. These need no model.
- **Model judge** for support and fact matching: an open-weights model
  served through any OpenAI-compatible endpoint, temperature 0, fixed seed.
  The prompt is versioned by its SHA-256 (`judge.py`, `PROMPT_VERSION`).
  Candidate facts and deposits are preselected lexically. The decision is
  the model's.
- **Judge validation before any publication, with no annotator** (amended
  2026-11-15; the thresholds below were committed before the first run).
  The first version of this section required the author to annotate ~100
  judge decisions blind (Cohen's κ ≥ 0.7). The author annotated 40 and
  stopped (results/README, "Judge validation"): on a sample where the
  judge calls 38 of 40 memories supported, κ says little, and the author
  will not annotate further. The gate is now three checks that need no
  one, and none of them is a validation against people:
  1. *Injected control* (§7): inventions injected at a known rate into the
     oracle's memories; the judge must recover the rate.
  2. *Mutation control* (`selfcheck`): memories written by a real system,
     which the judge called supported, are edited in code so the deposits
     no longer say them. A strict edit puts in a number, a first name or a
     city found in no deposit, so the twin is unsupported by construction;
     a loose edit (a shifted date, another person or city of the same
     world) is reported but not gated, since its truth rests on guards.
     Verbatim twins (the memory replaced by the excerpt it cites) are
     supported by construction. **Thresholds: the judge flags ≥ 0.90 of
     the strict twins and ≤ 0.10 of the verbatim twins.**
  3. *Second reader* (`annotate`, `reread`, `agreement --reader`): the
     stratified sample of ~100 judge decisions is labelled blind by another
     model than the judge, with the annotator's guide and only what an
     annotator would see. **Threshold: κ ≥ 0.7** on `support`, unchanged.
     Two models of one vendor can share blind spots; check 2, whose truth
     comes from code, is what covers that.
  A judge that misses a threshold is not used and the failure is published.
  Human annotation stays possible for anyone (`annotate`, `label`,
  `agreement`): the sample files are published so a reader can redo it.
- `LexicalJudge` is deterministic and used only to validate the harness on
  control systems and for smoke tests. It is never the published judge.

## 7. Controls (harness validation, not competitors)

| Control | Expected | Status |
|---|---|---|
| Oracle (reads the truth, cites the gold spans) | invention 0, excerpt support 1, recall 1, QA 1 | passes (tests) |
| Injected (oracle + inventions at rate *r*) | scorer recovers *r* | passes at 5 / 20 / 40 % (tests) |
| Always-abstain | QA = abstention share | passes (tests) |
| Oracle, attribution | attribution error 0, every memory measurable | passes (tests) |
| Injected misattribution (true content, wrong `subject` at rate *m*) | scorer recovers *m* within 0.03, invention unchanged | passes at 10 / 30 % (tests) |
| No declared subject | attribution `null` with a reason | passes (tests) |
| Oracle, identity links (proven when written together, inferred when converging) | alias recall 1, precision 1 at every snapshot | passes (tests) |
| Injected false links (*k* decoy links) | precision = n / (n + k), recall 1 | passes at k = 1, 3 (tests) |
| No links exposed | alias metrics `null` with a reason | passes (tests) |
| Oracle, bounded dates | every bounded_date answer correct, invented precision 0, store intervals justified | passes (tests) |
| Injected imprecision (one exact date for a share *p* of bounded_date answers) | scorer recovers *p* exactly | passes at 25 / 50 % (tests) |
| Abstaining on dates | invented precision 0, abstentions counted apart | passes (tests) |
| Verbatim (stores every sentence, lexical retrieval) | invention 0, low QA | invention 0, QA 0.16 on the sample |

## 8. Systems

Adapters share one contract (`adapters/base.py`).

- **Pensine**: implemented through public functions only (`append_event`,
  `nightly.consolidate`, the `memories` table, `recall`), on a throwaway
  database. Mode `llm` uses whatever backend is configured. Mode
  `scripted` replaces the consolidation model with a deterministic extractor
  that injects known inventions. It measures Pensine's code-level evidence
  gate, not its extraction.
- **Mem0, Zep, Supermemory, Memobase, ChatGPT memory, Claude memory**:
  documented skeletons, **never executed**. Running them is deferred until
  the protocol and the judge are validated. The consumer apps need a manual
  protocol because they have no export API.

## 9. License and ethics

- Data (truth, deposits, questions, media): **CC BY 4.0**.
  Code: Apache-2.0, like the rest of the repository.
- Fully synthetic. No real person, no real organisation, no real event.
  Photos are non-figurative by design.
- Voice, default engine: Chatterbox. The code
  (github.com/resemble-ai/chatterbox) and the model
  (huggingface.co/ResembleAI/chatterbox: metadata `license: mit`, README
  "Licensed under MIT") are MIT, checked 2026-10-28. The worker pins
  `chatterbox-tts` 0.1.7 (the full environment is frozen in
  `requirements-chatterbox.txt`) and the model revision
  `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`, and checks the SHA-256 of the
  five files it loads before loading them. Every output carries a Perth
  watermark (github.com/resemble-ai/perth, MIT, `resemble-perth` 1.0.1):
  imperceptible, it lets anyone check that a SOURCED voice memo is
  synthetic, which we count as a feature of the dataset. The voices are
  cloned from five ~10 s clips cut from LibriVox solo recordings of
  1813-1883 books (three female, two male, one of them British).
  librivox.org/pages/public-domain/ states that "all our recordings are
  public domain (definitely in the USA, and maybe in your country as well)";
  the texts are public domain everywhere their authors died more than a
  century ago, and each archive.org item carries a public-domain licence
  URL. Readers, files, segments and SHA-256 are in
  `sourced/voices/refs/REFS.md`. The clips voice fictional characters; no
  clip is presented as its reader.
- Voice, fallback engine: Piper (`piper-tts` 1.8.0,
  github.com/OHF-Voice/piper1-gpl). The
  code is GPL-3.0-or-later; it runs as a separate worker and its licence
  does not restrict the audio it produces. The voice repository
  (huggingface.co/rhasspy/piper-voices) is MIT. We use five voices whose
  training data is public domain, none derived from the research-only
  `lessac` voice. Each MODEL_CARD, at revision `5041a7a`, and the
  author's page (brycebeattie.com/files/tts/) state "License: public
  domain" for the dataset. Checked 2026-10-28:

  | Voice | Data | Training | Primary page |
  |---|---|---|---|
  | `en_US-ljspeech-medium` | LJ Speech (public domain, keithito.com/LJ-Speech-Dataset) | from scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_US/ljspeech/medium/MODEL_CARD) |
  | `en_US-kristin-medium` | LibriVox recordings | from scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_US/kristin/medium/MODEL_CARD) |
  | `en_US-norman-medium` | LibriVox recordings | from scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_US/norman/medium/MODEL_CARD) |
  | `en_US-john-medium` | LibriVox recordings | fine-tuned from `kristin` | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_US/john/medium/MODEL_CARD) |
  | `en_GB-cori-medium` | LibriVox recordings | from scratch | [MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_GB/cori/medium/MODEL_CARD) |

  The worker pins that revision and checks the SHA-256 of each `.onnx`.
  The Piper voices map to the slots in this order: `female_a` ljspeech,
  `female_b` kristin, `male_a` norman, `male_b` john, `female_gb` cori.
  Before 2026-10-28 the sample used Kokoro-82M, whose voice packs state no
  licence; it was replaced for that reason. Chatterbox replaced Piper as the
  default on 2026-10-28, on listening quality; the sample's committed voice
  files stay Piper until `scripts/regen_voices.sh` is run (the manifest's
  `audio` field says which engine made them).
- Health facts are benign and fictional.

## 10. Known limits

- Template-generated text is less varied than real life. An optional
  paraphrase layer (local model, re-verified against the spans) is
  planned, at the cost of exact-span guarantees.
- English only.
- Only Track T is wired for Pensine. Track R needs its media pipeline
  (transcription, vision) and is next.
- The lexical judge cannot read meaning. It is only a harness check.
- Attribution is measurable only for systems that declare a subject per
  memory. Pensine's adapter declares the entity Pensine itself resolved for
  each memory (migration 016: consolidation writes the subject as deposited,
  "my sister", and the code resolves it through an admitted identity claim).
  In scripted mode the rate is a real number but measures only the
  injected careless memories; the lexical judge cannot see the subject of
  an event memory that states no date, so the rate is a lower bound.
- Identity coverage is a template too: two attributes, one city each, one
  decoy of each kind. The alias metrics count links, not their use: a
  system that links correctly but answers through an unhedged inferred
  claim is not penalised here.
- Bounded dating covers one pattern ("not yet" then "already", day
  precision, inclusive bounds). Explicit dates, month-level bounds and
  contradicting bounds exist in Pensine's engine but not yet in the world.
  The lexical judge reads "not yet" memories by a word list.
- Identity-layer sentences are templates, and names are drawn without
  regard to the relation (a "brother" may be called Priya).
- Chatterbox samples speech tokens and flow-matching noise from torch. The
  worker seeds Python, NumPy and torch before the model is built and again
  per deposit, on CPU by default; reproducibility of Chatterbox files on the
  same machine is intended but not yet checked (MPS is not promised
  reproducible). Zero-shot cloning can drift from the reference voice; each
  file must be listened to before a release.
- Piper's graphs draw unseeded noise. The worker writes a per-deposit seed
  into them, so two runs with the same seed give byte-identical files on the
  same machine and library versions (checked twice on the 2-week sample).
  Bit-identity across machines is not promised. The manifest hashes the
  released files.

## Sources checked and rejected

Checked 2026-10-28. No arXiv identifier from the brief turned out to be
false. Details that did not survive the check:

- **"ReaLMem"**: the paper is spelled **RealMem** (arXiv 2601.06966). Its
  Findings of ACL 2026 venue appears only in search results, so it is not
  cited as a venue here.
- **LifeBench** (arXiv 2603.03781): the abstract does not state its
  modalities, its abstention handling or how facts change over time. It is
  not cited for any of them.
- **FEB-30 dataset**: the linked repository returned 404. We cite the paper,
  not the data or its license.
- **LoCoMo license**: the sources disagree (arXiv page CC BY-NC-SA 4.0,
  repository CC BY-NC 4.0). We cite the repository file.
- Code licenses of LongMemEval, ALCE and FActScore were not checked. They
  are not cited.

## AI use disclosure

The generator, harness, tests and this draft were written with an AI coding
assistant, working under the repository's research standards. The literature
check was done by an AI research agent against primary pages, and every
entry above comes from that check. The protocol choices and any conclusion
are the author's responsibility.
