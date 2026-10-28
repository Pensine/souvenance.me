# Verification log

**2026-10-28, first pass (cloud session).** arxiv.org, aclanthology.org, openreview.net,
huggingface.co and semanticscholar.org were blocked by that environment's network policy.
Entries confirmed on an author-controlled page (official repository or docs) went to
`references.bib`; entries seen only through a search index were *held* in `rejected.md`
and marked † in `related-work.md` and `positioning.md`.

**2026-10-28, second pass (local, arXiv API).** Every arXiv identifier cited in
`rejected.md` (28) was resolved through `export.arxiv.org/api/query`. All 28 exist, and the
title, author list and first-submission date returned by arXiv are recorded in
`arxiv-check-2026-10-28.tsv`. This lifts the two outright failures of the first pass:
ESAA (2602.23193, E. B. dos Santos Filho) and PsychoAgent (2608.07438, Amanlou et al.)
both resolve.

**What this pass does NOT verify.** Metadata only: no claim attached to a paper in
`related-work.md` was checked against its full text, and venues (EMNLP, ICLR, ACL…)
still come from the authors' repositories. Before any held entry moves into
`references.bib`, its cited claim must be read in the paper itself.
