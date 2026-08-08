# Research

Notes, position papers and evaluations produced alongside the engine.

## Why this folder exists

Souvenance makes a bet that is not primarily technical: **the memory should
outlive the model**. That claim deserves to be written down, argued against
the literature, and — where possible — measured. This folder is where that
happens, in the open, revision by revision.

## What goes in here

| Folder | Contents |
|---|---|
| `papers/` | Position papers and evaluations, one folder each, drafted in Markdown |
| `notes/` | Reading notes on the literature — raw material, not publications |
| `evals/` | Protocols, datasets and results for anything we claim to measure |

## Standards we hold ourselves to

**Every claim is either sourced, measured, or labelled as an opinion.** A
position paper without measurement is an argument, not evidence — and it says
so in its own abstract.

**Reproducibility over rhetoric.** Any number published here comes with the
protocol that produced it and the code to re-run it. Evaluations run on public
datasets, never on the author's private corpus: a result nobody can reproduce
is not a result.

**No citation enters a draft unverified.** AI research tools return plausible
references that do not exist, and figures attached to real papers that the
papers do not contain. Every source is checked against the primary document
before it is cited, and what fails the check is deleted rather than softened.
Each paper carries a visible list of the sources it rejected, so the filtering
can be audited instead of taken on trust.

**AI use is disclosed, never hidden.** Large language models assist with
drafting, literature synthesis and critique. They are not authors: every
claim, experiment and conclusion is the author's responsibility. Each paper
carries an explicit disclosure section.

**Negative results ship too.** If the temporal framing turns out not to help,
that is published here as well. The n=1 lab log already works that way.

## Publishing

Papers are archived on **Zenodo** for a citable DOI (GitHub release →
automatic archival). `CITATION.cff` at the repository root generates the
BibTeX entry through GitHub's "Cite this repository" button.

We do not submit to arXiv `cs.AI` for now: it requires endorsement from an
already-published author, which independent researchers rarely have. Zenodo
gives the same permanence and a DOI indexed by Google Scholar, without the
gatekeeping.

## Index

| Paper | Status | Claim |
|---|---|---|
| [001 — The substrate thesis](papers/001-substrate-thesis/) | [draft v0.1](papers/001-substrate-thesis/paper.md) | A memory system stays relevant across AI generations *because* it presupposes their obsolescence |
| [002 — Lived time](papers/002-lived-time/) | [protocol](papers/002-lived-time/README.md) | Time framing computed in code beats leaving temporal arithmetic to the model — measured by ablation on LoCoMo, across a capability range |
