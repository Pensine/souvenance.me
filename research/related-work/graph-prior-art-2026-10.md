# Prior art: an evidenced memory graph (check of 2026-10-28)

Abstracts opened on arXiv unless marked UNVERIFIED. Full text read for RECON only.

## 1. Evidenced identity resolution + attribution error: PARTIALLY DONE, core likely novel
- SocialMemBench 2605.17789 (Owolabi, 2026-05): group chats, "entity merging", attribution. Not owner life-logs, no stored alias decisions.
- GroupMemBench 2605.14498 (Yang, 2026-05): asker-specific questions, per-speaker beliefs.
- SpeakerMem-R1 2609.26780 (Zheng, 2026-09): speaker-aware memory, reward against attribution errors; no alias/pronoun resolution metric.
- MemSyco-Bench 2607.01071 (Xiang, 2026-07): memory scope.
- Graphiti (code, dedupe_nodes.py): name/embedding candidates then LLM returns a duplicate id; no excerpt, confidence or unmerge stored. Cognee merges at 0.85 and deletes (UNVERIFIED).
Defensible gap: each alias/identity decision stored as a sourced, revisable claim; attribution error reported as its own metric on single-owner multimodal life-logs.

## 2. Conflict vs change: PARTIALLY DONE, close to done
- StateFuse 2607.05844 (Volkov, 2026-07): immutable history, explicit conflict objects resolved at read.
- TOKI 2606.06240 (Wang, 2026-06): bitemporal contradiction algebra, audit rows.
- RECON 2607.16716 (Arya, 2026-07): source-conflict task, but always one resolving source.
- STALE 2605.06527 (Chao, 2026-05): silently superseded memories.
Defensible gap (narrow): scoring rule separating a change over valid time from a disagreement between sources about the same time; surfacing both counts as correct.

## 3. Bounded dating: NOVEL-LIKELY within agent memory
- ChronoSense 2501.03040 (Islakoglu, 2025-01): Allen relations over given dates.
- When Silence Is Golden 2602.04755 (Zhou, 2026-02): temporal abstention, all-or-nothing.
- Temporal Semantic Memory 2601.07468 (Su, 2026-01): event-time memory, no uncertain bounds.
- Agent Zero Memory 2608.29606 (Wu, 2026-08): evidence pointers, abstention.
Defensible gap: earliest/latest bounds each backed by a quote; justified interval answers; "invented precision" metric.

## Ranking
1 identity (needs corpus + metric, hard to copy), 3 bounded dating (clear gap, easy mechanism), 2 conflict (crowded, only the scoring rule).

## Do not claim
First bi-temporal or edge invalidation; first to keep conflicts; first attribution/speaker benchmark; first source-conflict questions; first extraction-hallucination benchmark; first provenance memory; first temporal-interval benchmark; "no system does entity resolution"; novelty of temporal abstention.
Not yet covered: classic coreference/entity linking over long dialogue; A-Mem, MemoryOS, Letta internals.

## Addendum: two-tier identity links (PROVEN / INFERRED), check of 2026-10-28
Verdict: PARTIALLY DONE. The concept is classic; only the integration and its evaluation may be ours.
- Mem0 (26cdefb, mem0/memory/main.py `_upsert_entity`): exact name or cosine >= 0.95, no confidence, tiers, excerpts or unmerge.
- Graphiti (b1c609f, dedup_helpers.py, node_operations.py, prompts/dedupe_nodes.py): identity props, exact name, MinHash >= 0.9, then LLM (-1 when unsure); binary IS_DUPLICATE_OF edges, irreversible merge.
- Cognee (37f788b, ontology matching_strategies.py): difflib 0.8, binary. LightRAG (aaebfe1): same-name merge, keeps source chunk ids and evidence counts.
- H-Mem 2605.15701 (Yu, 2026-05): "overlap edge" that is not identity, retrieval only. Closest published not-yet-identity link.
- Hindsight (vendor blog, 2026-06): weighted score, one threshold, binary, no unmerge.
- Supermemory blog (2026-07-20): advises keeping inferred matches distinguishable from confirmed ones, with provenance. Advice, no implementation found.
- Record linkage: Fellegi-Sunter 1969 possible links + clerical review (secondary sources); Splink per-pair match weights and evidence; Lam et al. IJPDS 2026 review bands.
- Personal entity linking: Joko et al. 2206.07836, ConEL 2105.04903; Balog & Kenter PKG (ICTIR 2019).
- Provenance gates: "Stored Is Not Supported" 2609.02127; Eywa 2605.30771.
Defensible: in a single-owner multimodal memory, the combination of PROVEN/INFERRED links, inference only from >= 2 independent quote-checked attributes (or channel metadata), confidence from independent supports not an LLM verdict, hedged use only and no new facts attached until promotion, closure with a reason, and a benchmark of alias precision/recall per tier with attribution error. The integration and the evaluation, not the concept.
Do not claim: tiered/possible matches; per-link evidence; keeping inferred apart from confirmed; first non-merging alias link; first provenance-gated memory; first personal entity linking; that agent memories never handle uncertainty.
UNVERIFIED: Letta, MemoryOS, MIRIX, LangMem, Memobase, Zep cloud internals, Zep and Mem0 papers, Dedupe.io, the 1969 paper itself.
