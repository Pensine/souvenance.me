# Reading notes — world models and JEPA

Raw material for paper 001. Not a publication.

## Primary source

Maes, L., Le Lidec, Q., Scieur, D., LeCun, Y., Balestriero, R. (2026).
*LeWorldModel: Stable End-to-End Joint-Embedding Predictive Architecture from
Pixels.* arXiv:2603.19312v3, 3 June 2026.

### What the paper does

Trains a **world model** — a predictive model of environment dynamics — end to
end from raw pixels, in a compact latent space, with only two loss terms: a
next-embedding prediction loss and an anti-collapse regulariser (SIGReg,
enforcing Gaussian-distributed latents). ~15M parameters, one GPU, a few
hours. Plans up to 48× faster than foundation-model-based world models while
staying competitive on 2D and 3D control tasks.

### The claims that matter for us

**Predict in latent space, do not reconstruct.** "Instead of attempting to
model every aspect of the environment, JEPA focuses on capturing the most
relevant features needed to predict future states." Reconstruction of the raw
signal is explicitly rejected as the objective.

**Reward-free and task-agnostic.** The model is trained on unannotated
trajectories, "not to optimise behaviour for a specific task, but to learn
representations that capture environment dynamics and can later be controlled
or adapted to a diverse set of tasks."

**Planning happens in imagination.** At inference the system rolls out
predicted latent states over a horizon and optimises an action sequence
against a goal embedding — it thinks before it acts, in latent space.

**Surprise is measurable.** A violation-of-expectation test detects
physically implausible trajectories: the gap between prediction and
observation is itself a usable signal.

**The structure emerges without supervision.** Probing recovers physical
quantities (positions, angles) from latents that were never trained to encode
them.

## Where this touches Souvenance

Four correspondences, and they are structural rather than superficial.

**1. Compression by prediction, not by storage.** JEPA discards what is not
predictive of the future. Nightly consolidation discards what is not
significant — importance scoring, active forgetting, gists for old memories.
Both refuse the reconstruction objective: the raw signal is kept
(originals-forever), but the *learned* layer is deliberately lossy.

**2. Surprise as the learning signal.** The paper's violation-of-expectation
test is the same shape as the prediction-error loop in the founding document
(Friston, a mind that learns only from the delta): predict the subject, measure
the gap, learn from the gap. In LeWM it detects impossible physics; here it
would detect a self-model drifting from the person.

**3. Dynamics over snapshots.** A world model learns *how things change*, not
what they are at time t. That is the temporal knowledge graph: facts with
validity intervals, contradicted edges closed but never deleted, landmarks as
coordinates. Both encode trajectory rather than state.

**4. Capability before purpose.** "Learn representations that capture dynamics
and can later be adapted to diverse tasks" is, word for word, the founding
document's directing principle: *build the memory before knowing everything it
will be used for.*

## Where the analogy breaks — and it must be stated

A world model is **predictive and prospective**: it exists to plan, to act, to
imagine forward. A personal memory is **retrospective and reconstructive**: it
exists to situate, to retrieve, to relive. LeWM models a physical environment
shared by everyone; Souvenance models one irreproducible life.

More importantly: LeWM's latents are **not portable**. They are meaningful only
inside the encoder that produced them — retrain the encoder and the latents are
garbage. This is precisely why Souvenance keeps the *event log*, not the
embeddings, as the source of truth: embeddings are a derived index that any
future model can recompute. Confusing the two would be the architectural
mistake this paper helps articulate.

## The argument this source unlocks

LeCun's programme is a bet that today's dominant architecture is not the end
state — that reaching human-level understanding requires world models learning
dynamics in latent space, not larger autoregressive text predictors.

Take that seriously and the conclusion is uncomfortable for most AI products:
**the interface layer being built against today's models is scheduled for
obsolescence by the very people building tomorrow's.** A memory system coupled
to a specific model generation inherits that expiry date.

An append-only substrate does not. Rejecting the log through a 2036 engine is a
migration, not a rewrite. That is the whole thesis of paper 001 — and this
paper is its strongest external witness, because the argument comes from
someone building the replacement rather than from someone defending the
incumbent.
