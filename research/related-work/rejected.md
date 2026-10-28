# Rejected / held citations — verification log (2026-10-28)

Method: each candidate had to be confirmed on a primary page (title, authors, year, venue, claim).
Environment limit: arxiv.org, aclanthology.org, openreview.net, huggingface.co, semanticscholar.org,
alphaxiv.org and docs.openclaw.ai were all **blocked by the network policy**. Only GitHub raw content
and a web-search index were reachable. Candidates confirmed only through the search index never had their
primary page opened, so they **fail the rule** and are listed here. They are *not refuted*.

## A. Failed — identifier or metadata could not be established

| Candidate | Reason |
|---|---|
| ESAA, arXiv 2602.23193 | No arXiv listing found at this ID in two searches (one extended). Secondary sources name "ESAA: Event Sourcing for Autonomous Agents in LLM-Based Software Engineering" (E. B. dos Santos Filho), but none ties it to 2602.23193. Related ESAA-Security is arXiv 2603.06365 (unverified). **Do not cite.** |
| PsychoAgent, arXiv 2608.07438 | The search index shows the title "PsychoAgent: An Affect-Sensitive Cognitive Architecture for Conflict-Aware Memory in LLM Agents" but **no authors and no abstract**. Unrelated papers share the name (a panic-prediction PsychoAgent on ACL Anthology). Metadata incomplete. |

## B. Held — found only via search index, primary page not opened (re-verify on arXiv before use)

Each entry records what the index showed. † marks them in related-work.md and positioning.md.

| Candidate | Index-reported metadata | Notes / discrepancies |
|---|---|---|
| MemGPT 2310.08560 | "MemGPT: Towards LLMs as Operating Systems", Packer, Fang, Patil, Lin, Wooders, Gonzalez; v1 Oct 2023 | Author order differs between abstract page and PDF. Letta repo confirms only "f.k.a. MemGPT", with no paper citation. |
| Zep 2501.13956 | "Zep: A Temporal Knowledge Graph Architecture for Agent Memory", Rasmussen, Paliychuk, Beauvais, Ryan, Chalef; Jan 2025 | Graphiti repo confirms title prefix and ID but not authors. The bi-temporal claim is cited via the verified repo entry `graphiti2025repo`. |
| FEB-30 2610.22209 | "Beyond Downstream QA: Rethinking How We Evaluate Agent Memory", Toma, de Kernier, Ply, Matei; 15 Oct 2026 | "FEB-30" is the benchmark name, not the title. Very recent. |
| Ground Truth First 2607.21962 | "Ground Truth First: A Longitudinal Evaluation Instrument for Agent Memory, and the Tenure Crossover in Memory-Architecture Rankings", Quentin Spencer; Jul 2026 | Single independent author; library "Veracium". |
| Selective QA 2605.30087 | "Selective QA over Conflicting Multi-Source Personal Memory: A Diagnostic Testbed and Method Comparison", Tiancheng Yang, Matthias Schonlau, Ilia Sucholutsky; May 2026 | — |
| ProMem 2601.04463 | "Beyond Static Summarization: Proactive Memory Extraction for LLM Agents", Chengyuan Yang, Zequn Sun, Wei Wei, Wei Hu; Jan 2026 | "ProMem" is the method name. |
| Fidelity Before Structure 2601.00821 | "Fidelity Before Structure: Verbatim Chunks Beat Lossy Artifact Extraction in Long-Conversation LLM Memory", Tao An | **Title changed across versions**: v1 was "CogCanvas: Verbatim-Grounded Artifact Extraction for Long LLM Conversations". Cite the version actually read. |
| HeLa-Mem 2604.16839 | "HeLa-Mem: Hebbian Learning and Associative Memory for LLM Agents", Jinchang Zhu, Jindong Li, Cheng Zhang, Jiahong Liu, Menglin Yang; Apr 2026 | Index claims ACL 2026; not verified. |
| SCM 2604.20943 | "SCM: Sleep-Consolidated Memory with Algorithmic Forgetting for Large Language Models"; Apr 2026 | **Authors not shown** in index. Acronym collides with "Self-Controlled Memory" (2023). |
| TReMu 2502.01630 | "TReMu: Towards Neuro-Symbolic Temporal Reasoning for LLM-Agents with Memory in Multi-Session Dialogues", Ge, Romeo, Cai, Shu, Sunkara, Benajiba, Zhang | Index says Findings of ACL 2025. |
| TSM 2601.07468 | "Beyond Dialogue Time: Temporal Semantic Memory for Personalized LLM Agents", Miao Su et al. (11 authors) | Index says Findings of ACL 2026. Full author list not seen. |
| Second Me 2503.08102 | "AI-native Memory 2.0: Second Me", Wei, Ying, Gao, Bao, Tao, Shang | Repo (mindverse/Second-Me) links the ID but gives no authors; author lists differ between PDF and HTML. |
| MemMachine 2604.04853 | "MemMachine: A Ground-Truth-Preserving Memory System for Personalized AI Agents", Shu Wang et al. (MemVerge); Apr 2026 | Repo README has no paper citation. |
| Spotlighting 2403.14720 | "Defending Against Indirect Prompt Injection Attacks With Spotlighting", Keegan Hines et al. (Microsoft); Mar 2024 | Full author list not seen. |
| A-MemGuard 2510.02373 | "A-MemGuard: A Proactive Defense Framework for LLM-Based Agent Memory", Wei et al.; Sep 2025 | Full author list not seen. |
| MINJA 2503.03704 | v1 "A Practical Memory Injection Attack against LLM Agents"; v5 "Memory Injection Attacks on LLM Agents via Query-Only Interaction"; Dong, Xu, He, Li, Tang, Liu, Liu, Xiang | **Title changed**; one author's first name is inconsistent (Shaocheng/Shaochen). |
| AgentPoison | — | **Not rejected**: verified as `chen2024agentpoison` (arXiv 2407.12784). |
| AttributionBench | — | **Not rejected**: no ID given; resolved to arXiv 2402.15089 and verified. |
| Algorithmic Self-Portrait 2602.01450 | "The Algorithmic Self-Portrait: Deconstructing Memory in ChatGPT", Dash, Das, Kirsten, Wu, Karnam, Gummadi, Holz, Zafar, Zannettou | WWW 2026 acceptance reported by the index only. A first, non-ID search failed to find it. |
| LifeBench 2603.03781 | "LifeBench: A Benchmark for Long-Horizon Multi-Source Memory", Zihao Cheng … Cam-Tu Nguyen (18 authors); Mar 2026 | Name collides with LIFEBench (length instruction following). |
| ReaLMem 2609.19167 | "To Memories and Beyond: From Remembering to Knowing You across Long-Term Multimodal Personal Archives", Wenqi Zhou et al.; Sep 2026 | Name collides with RealMem (Findings ACL 2026) and REALM 2609.16053. |
| LifeDialBench 2604.11182 | "Evaluating Memory Capability in Continuous Lifelog Scenario", Jianjie Zheng et al.; Apr 2026 | "LifeDialBench" is the benchmark name, not the title. A first, name-based search failed. |
| Agent Zero Memory 2608.29606 | "Agent Zero Memory: Provenance-Aware Long-Term Memory for LLM Agents", Ming Wu, Pengyuan Zhu; Aug 2026 | — |
| MemPalace critique 2604.21284 | "Spatial Metaphors for LLM Memory: A Critical Analysis of the MemPalace Architecture"; Apr 2026 | **Authors not shown.** |

## C. Notes on verified entries (not rejected, but flagged)
- HaluMem: the repo README heading reads "HaluMem: A Comprehensive Benchmark for Evaluating Hallucinations in Memory Systems", while the authors' BibTeX title is "…Memory Systems of Agents". BibTeX lists 9 authors; a search summary said 11.
- OpenClaw Dreaming: the repo doc says dreaming is **enabled by default**; a search summary of docs.openclaw.ai said opt-in and off by default. Report the version read.
- TwinVoice: ACL 2026 vs Findings of ACL 2026 is unresolved.
