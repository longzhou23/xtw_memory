# Codex Modification Spec — Memory Demo Three-Relation Attention Dynamics P0.2

**Project:** 小天文 Memory / Associative Memory Demo  
**Target repository:** current `memory-demo` implementation  
**Task type:** narrow revision of the existing visual demo  
**Status:** IMPLEMENTATION SPEC  
**Do not redesign the model. Implement exactly this revision.**

---

# 0. Why this revision exists

The current demo successfully visualizes conserved attention diffusion, but the B1 case:

> “小天文喵是谁做出来的？”

shows a failure mode:

- `小天文` remains highly active;
- `longz / creator memory` receives some attention;
- but `流星雨 / 天文观测 / 天文社社娘 / 其他相似关联` also receive comparable non-trivial attention;
- the result looks like **attention dispersion**, not focused recall.

This is not only a UI issue.

The current engine has two conceptual problems:

1. **Context only seeds nodes; it does not represent the current relation direction of thought.**
2. **High-degree nodes can leak attention across many outgoing associations.**

A third missing mechanism is also now explicit:

3. **Conservation alone does not create cognitive focus; global competition is required.**

This revision changes the dynamics while preserving the original core hypothesis:

> Recall is constrained attention diffusion over a heterogeneous associative network, not Top-K retrieval.

---

# 1. Frozen conceptual model

The associative layer has only **three relation types**:

```text
CAUSAL
SIMILARITY
OPPOSITION
```

Do NOT add:

```text
created_by
likes
located_in
owns
has_role
plays
contains
member_of
...
```

as engine-level relation types.

Those precise semantics belong in:

- Node content;
- Memory content;
- Proposition content;
- metadata.

The associative engine only reasons over:

```text
Node
Association Strength
Relation Type
Attention
Context
Competition
```

---

# 2. Responsibilities of the three relation types

## 2.1 CAUSAL

Represents:

```text
cause → effect
source → consequence
reason → result
origin → produced object/state
```

The stored edge direction is meaningful:

```text
source = cause
target = effect
```

Example:

```text
longz --CAUSAL--> 小天文
```

A recall process may traverse this edge:

```text
forward:
longz → 小天文

reverse:
小天文 → longz
```

Reverse traversal does NOT create a new semantic relation.
It is simply causal reasoning in the reverse direction.

---

## 2.2 SIMILARITY

Represents broad associative closeness:

```text
semantic similarity
co-occurrence
same topic
ordinary association
same cognitive cluster
alias-like closeness
```

It is treated as **symmetric for traversal** in P0.2.

A single stored edge:

```text
A --SIMILARITY-- B
```

must be traversable:

```text
A → B
B → A
```

Do not require duplicate reverse edges in the dataset.

---

## 2.3 OPPOSITION

Represents:

```text
contrast
conflict
opposite state
mutual exclusion
counterexample
```

It is also treated as **symmetric for traversal** in P0.2.

A single stored edge:

```text
A --OPPOSITION-- B
```

must be traversable in both directions.

---

# 3. Exact current implementation that must be replaced

Current `src/engine/diffusion.ts` builds fixed transitions in `buildTransitions()`:

```ts
const logits = edges.map((edge) =>
  Math.exp(edge.associationStrength / t)
);

const selfShare = parameters.selfRetention;

share =
  (1 - selfShare)
  * logits[index]
  / denominator;
```

This means:

```text
active node
→ always keeps a fixed selfRetention fraction
→ always distributes the remaining fraction
→ outgoing edge weights only compete relatively
```

This is no longer the intended model.

Remove this transition-matrix behavior from the actual simulation path.

`buildTransitions()` may be deleted or replaced by a helper that builds traversal arcs / adjacency only.

---

# 4. New data model

Modify `src/types.ts`.

## 4.1 Relation type

Add:

```ts
export type AssociationRelation =
  | 'CAUSAL'
  | 'SIMILARITY'
  | 'OPPOSITION';
```

---

## 4.2 MemoryEdge

Replace the engine-level free-form `relation: string` with:

```ts
export interface MemoryEdge {
  id: string;

  source: string;
  target: string;

  relationType: AssociationRelation;

  associationStrength: number;

  evidence?: string[];
  metadata?: Record<string, unknown>;
}
```

Do not use `metadata.semanticHint` in numerical diffusion.

It may exist for human inspection only.

---

# 5. Relation Context

Current RecallCase only contains:

```ts
initialAttention
```

Add a relation context.

```ts
export interface RelationContext {
  causal: number;
  similarity: number;
  opposition: number;

  causalDirection: 'forward' | 'reverse' | 'both';
}
```

Then:

```ts
export interface RecallCase {
  id: string;
  title: string;
  description?: string;

  context: string;

  initialAttention: Record<string, number>;

  relationContext: RelationContext;

  expectedEmergence: string[];
  distractors?: string[];
  tags?: string[];
}
```

---

# 6. Relation Context invariant

Require:

```text
causal >= 0
similarity >= 0
opposition >= 0
```

and:

```text
causal + similarity + opposition > 0
```

Normalize the three weights to sum to 1 when loading the case.

Example:

```json
{
  "causal": 0.85,
  "similarity": 0.10,
  "opposition": 0.05,
  "causalDirection": "reverse"
}
```

Interpretation:

> The current thought is mainly causal, and is tracing backward from an effect toward a cause.

This is the intended profile for:

```text
“小天文喵是谁做出来的？”
```

---

# 7. Default Relation Context

For old/simple cases or manually created test fixtures, the default may be:

```ts
{
  causal: 0.15,
  similarity: 0.80,
  opposition: 0.05,
  causalDirection: 'both'
}
```

But do NOT silently apply this to a production dataset that is explicitly versioned for the new model and missing relationContext.

For the new dataset schema, missing relationContext should fail validation.

The default is only for unit-test construction helpers if useful.

---

# 8. New diffusion parameters

Replace the current:

```ts
selfRetention
propagationFloor
```

with:

```ts
flowPotentialFloor
maxOutflowFraction
competitionGamma
```

The complete interface becomes:

```ts
export interface DiffusionParameters {
  temperature: number;

  flowPotentialFloor: number;
  maxOutflowFraction: number;

  competitionGamma: number;

  contextAnchor: number;
  emergenceThreshold: number;

  maxSteps: number;
  stepInterval: number;
}
```

Suggested P0.2 defaults:

```ts
export const DEFAULT_PARAMETERS: DiffusionParameters = {
  temperature: 1.0,

  flowPotentialFloor: 0.01,
  maxOutflowFraction: 0.45,

  competitionGamma: 1.5,

  contextAnchor: 0.12,
  emergenceThreshold: 0.10,

  maxSteps: 12,
  stepInterval: 600,
};
```

These are demo defaults, not scientifically frozen constants.

---

# 9. Parameter meanings

## temperature

Controls how strongly static association strength differences matter:

\[
G_{base}=S^{1/T}
\]

---

## flowPotentialFloor

Minimum current flow potential required for a traversal arc to participate.

It replaces the old node-level `propagationFloor`.

---

## maxOutflowFraction

Maximum fraction of a node's current attention that can leave the node in one step.

This prevents high-degree hub nodes from “leaking” most of their attention simply because they have many associations.

---

## competitionGamma

Global sharpening / lateral competition exponent.

Require:

```text
competitionGamma >= 1
```

where:

```text
1.0 = no sharpening
>1   = increasing competition
```

---

# 10. Traversal arcs

The stored graph and the current traversal graph are not identical.

Build transient traversal arcs for the selected RecallCase.

Define:

```ts
interface TraversalArc {
  edgeId: string;

  source: string;
  target: string;

  relationType: AssociationRelation;

  traversalDirection:
    | 'forward'
    | 'reverse'
    | 'symmetric';

  associationStrength: number;
}
```

---

# 11. Traversal rules

For every stored edge:

## CAUSAL

Stored:

```text
source(cause) → target(effect)
```

If:

```text
causalDirection = forward
```

create:

```text
source → target
```

If:

```text
causalDirection = reverse
```

create:

```text
target → source
```

If:

```text
causalDirection = both
```

create both traversal arcs.

Both arcs reference the same original `edgeId`.

---

## SIMILARITY

Always create:

```text
source → target
target → source
```

Both are marked:

```text
traversalDirection = symmetric
```

---

## OPPOSITION

Same as SIMILARITY:

```text
source → target
target → source
```

---

# 12. Relation gate

For each traversal arc, derive:

```ts
relationGate =
  relationType === 'CAUSAL'
    ? relationContext.causal
    : relationType === 'SIMILARITY'
      ? relationContext.similarity
      : relationContext.opposition;
```

Because relationContext is normalized:

```text
0 <= relationGate <= 1
```

---

# 13. Effective association

For traversal arc \(i \to j\):

\[
\boxed{
G_{ij}
=
S_{ij}^{1/T}
\cdot
R_{ij}(C)
}
\]

where:

```text
S_ij = associationStrength
T    = temperature
R    = relationGate
```

Implementation:

```ts
const baseAssociation =
  Math.pow(edge.associationStrength, 1 / temperature);

const effectiveAssociation =
  baseAssociation * relationGate;
```

Do NOT apply softmax across outgoing edges here.

---

# 14. Attention-dependent flow potential

For node \(i\) with current attention \(A_i\):

\[
\boxed{
Q_{ij}
=
A_i
\cdot
G_{ij}
}
\]

Implementation:

```ts
const flowPotential =
  sourceAttention * effectiveAssociation;
```

This is the value that determines whether an edge can participate in this step.

---

# 15. Eligibility

Use:

\[
\boxed{
E_{ij}
=
\max
\left(
0,
Q_{ij}
-
\theta_{flow}
\right)
}
\]

where:

```text
θ_flow = flowPotentialFloor
```

If:

```text
E_ij <= 0
```

the traversal arc is inactive.

Important:

Do NOT:

```text
take top N outgoing edges
```

Do NOT:

```text
always distribute some fixed fraction
```

The active frontier must emerge from current attention × association × context.

---

# 16. Bounded outflow

For source node \(i\):

\[
requested_i
=
\sum_j E_{ij}
\]

Its maximum allowed outflow:

\[
budget_i
=
L_{max}A_i
\]

where:

```text
L_max = maxOutflowFraction
```

Actual outflow:

\[
\boxed{
O_i
=
\min
\left(
budget_i,
requested_i
\right)
}
\]

This is the anti-hub mechanism.

A node with 3, 30, or 300 eligible associations cannot send more than:

```text
maxOutflowFraction × currentAttention
```

in one step.

---

# 17. Local allocation

If:

```text
requested_i > 0
```

then:

\[
\boxed{
F_{ij}
=
O_i
\frac{E_{ij}}{\sum_kE_{ik}}
}
\]

and local retention is:

\[
\boxed{
F_{ii}
=
A_i-O_i
}
\]

If there are no eligible arcs:

```text
F_ii = A_i
```

The node keeps all of its attention.

---

# 18. Local conservation

For each source node:

\[
F_{ii}
+
\sum_jF_{ij}
=
A_i
\]

This should hold numerically before any global competition step.

Add an assertion in development/tests.

---

# 19. Multi-path convergence

After all sources are processed:

\[
\boxed{
D_j
=
\sum_iF_{ij}
}
\]

All incoming paths add.

Never use:

```text
max
average
winner-only
dedup strongest path
```

Multi-path accumulation remains a core mechanism.

---

# 20. Global competition / sharpening

After raw diffusion produces \(D\):

\[
\boxed{
B_j=D_j^\gamma
}
\]

where:

```text
γ = competitionGamma
```

Then normalize:

\[
\boxed{
H_j
=
\frac{B_j}{\sum_kB_k}
}
\]

Properties:

```text
competitionGamma = 1
→ H = D

competitionGamma > 1
→ stronger nodes gain relative advantage
→ weak branches are suppressed
```

This is the mechanism that converts diffuse activation into cognitive focus.

---

# 21. Context reinjection

Let:

```text
C = normalized initialAttention
```

Then:

\[
\boxed{
A_j(t+1)
=
(1-\lambda)H_j
+
\lambda C_j
}
\]

where:

```text
λ = contextAnchor
```

Because:

```text
sum(H) = 1
sum(C) = 1
```

therefore:

\[
\sum_jA_j(t+1)=1
\]

without substantive renormalization.

---

# 22. No normalization as an error-hiding mechanism

The current code calls:

```ts
normalizeAttention(...)
```

on every step.

Replace this behavior.

The algorithm should already conserve one unit of attention.

Use normalization only for tiny floating-point drift.

Recommended:

```ts
const total = sum(nextAttention);

if (Math.abs(total - 1) > 1e-9) {
  throw new Error(
    `Attention conservation failed before correction: ${total}`
  );
}
```

If needed, correct only tiny epsilon drift.

Do not silently repair a materially incorrect total.

---

# 23. Full step pseudocode

Implement the numerical logic approximately as follows.

```ts
function step(
  dataset: DemoDataset,
  attention: Record<string, number>,
  context: Record<string, number>,
  relationContext: RelationContext,
  parameters: DiffusionParameters,
): DiffusionStepInternal {

  const traversalArcs =
    buildTraversalArcs(dataset.edges, relationContext);

  const outgoing =
    groupTraversalArcsBySource(traversalArcs);

  const diffused = zeroVector(dataset.nodes);

  const edgeFlows: EdgeFlow[] = [];
  const nodeFlowStats: Record<string, NodeFlowStats> = {};

  for (const node of dataset.nodes) {
    const source = node.id;
    const Ai = attention[source] ?? 0;

    const eligible = [];

    for (const arc of outgoing.get(source) ?? []) {
      const gate =
        relationGate(
          arc.relationType,
          relationContext
        );

      const base =
        Math.pow(
          arc.associationStrength,
          1 / parameters.temperature
        );

      const effective =
        base * gate;

      const flowPotential =
        Ai * effective;

      const excessPotential =
        Math.max(
          0,
          flowPotential
            - parameters.flowPotentialFloor
        );

      recordArcDebug(...);

      if (excessPotential > 0) {
        eligible.push({
          arc,
          effective,
          flowPotential,
          excessPotential,
        });
      }
    }

    const requested =
      sum(eligible.map(x => x.excessPotential));

    const outflowBudget =
      parameters.maxOutflowFraction * Ai;

    const actualOutflow =
      Math.min(
        outflowBudget,
        requested
      );

    const retained =
      Ai - actualOutflow;

    diffused[source] += retained;

    if (requested > 0 && actualOutflow > 0) {
      for (const item of eligible) {
        const flow =
          actualOutflow
          * item.excessPotential
          / requested;

        diffused[item.arc.target] += flow;

        recordEdgeFlow(...);
      }
    }

    nodeFlowStats[source] = {
      heldAttention: Ai,
      eligibleEdgeCount: eligible.length,
      requestedOutflow: requested,
      outflowBudget,
      actualOutflow,
      retainedAttention: retained,
    };
  }

  assertApproximatelyEqual(sum(diffused), 1);

  // competition
  const sharpenedRaw = {};
  for (const node of dataset.nodes) {
    sharpenedRaw[node.id] =
      Math.pow(
        diffused[node.id],
        parameters.competitionGamma
      );
  }

  const sharpenedTotal =
    sum(Object.values(sharpenedRaw));

  const competed = {};
  for (const node of dataset.nodes) {
    competed[node.id] =
      sharpenedRaw[node.id]
      / sharpenedTotal;
  }

  // context anchor
  const next = {};
  for (const node of dataset.nodes) {
    next[node.id] =
      (1 - parameters.contextAnchor)
        * competed[node.id]
      +
      parameters.contextAnchor
        * context[node.id];
  }

  assertApproximatelyEqual(sum(next), 1);

  return {
    attention: next,
    edgeFlows,
    nodeFlowStats,
    ...
  };
}
```

---

# 24. Diffusion diagnostics

Current `EdgeFlow` only stores:

```ts
transitionShare
attentionCarried
```

That is insufficient for the new model.

Replace it with:

```ts
export interface EdgeFlow {
  edgeId: string;

  source: string;
  target: string;

  relationType: AssociationRelation;
  traversalDirection:
    | 'forward'
    | 'reverse'
    | 'symmetric';

  associationStrength: number;

  relationGate: number;
  effectiveAssociation: number;

  flowPotential: number;
  excessPotential: number;

  eligible: boolean;

  attentionCarried: number;
}
```

There is no longer a meaningful fixed:

```text
transitionShare
```

Remove it.

---

# 25. Node flow diagnostics

Add:

```ts
export interface NodeFlowStats {
  heldAttention: number;

  eligibleEdgeCount: number;

  requestedOutflow: number;
  outflowBudget: number;
  actualOutflow: number;

  retainedAttention: number;
}
```

Add to `DiffusionStep`:

```ts
nodeFlowStats:
  Record<string, NodeFlowStats>;
```

This is important for debugging hub behavior.

---

# 26. IncomingContribution

Extend:

```ts
export interface IncomingContribution {
  source: string;
  amount: number;

  edgeId?: string;

  relationType?: AssociationRelation;
  traversalDirection?:
    | 'forward'
    | 'reverse'
    | 'symmetric';

  isSelfRetention?: boolean;
}
```

---

# 27. Active node definition

Remove the old meaning:

```text
activeNode =
attention >= propagationFloor
```

A node is considered active in a step if:

```text
it has attention > numerical epsilon
AND
at least one traversal arc is eligible
```

Use a small implementation epsilon such as:

```ts
const ATTENTION_EPSILON = 1e-12;
```

This is not a user-adjustable cognitive parameter.

---

# 28. Validation changes

Modify `src/engine/validation.ts`.

Validate every edge:

```text
relationType ∈ {
  CAUSAL,
  SIMILARITY,
  OPPOSITION
}
```

Unknown relation types must fail loudly.

Do not auto-map:

```text
created_by
likes
has_cue
located_in
...
```

inside the validator.

The current annotated datasets require separate semantic re-annotation.

---

# 29. Dataset migration boundary

Important:

The existing files contain many free-form relations such as:

```text
has_cue
evokes_memory
created_by
known_as
plays
located_in
...
```

Codex must NOT invent an automatic mapping from them to the three new relation types.

Do not do:

```text
all unknown relation → SIMILARITY
```

Do not infer:

```text
created_by → CAUSAL
```

automatically across the production data.

The code change and the data re-annotation are separate responsibilities.

For development/tests, use a small explicitly authored three-relation fixture.

The final large dataset will be re-annotated separately.

---

# 30. Dataset version

Use a new dataset schema version:

```text
0.3.0
```

The new app should reject legacy datasets lacking `relationType` and `relationContext`, with a clear error such as:

```text
Dataset schema requires three-relation annotation (v0.3+).
Legacy free-form relations are not auto-migrated.
```

Do not silently fall back to the old engine.

---

# 31. Required B1 regression fixture

Create a small explicit test fixture for:

> “小天文喵是谁做出来的？”

Suggested graph:

```text
小天文喵
  --SIMILARITY 0.95--
小天文

longz
  --CAUSAL 0.95-->
小天文

小天文
  --SIMILARITY 0.80--
流星雨

小天文
  --SIMILARITY 0.80--
天文观测

小天文
  --SIMILARITY 0.80--
华理天文社社娘
```

Case:

```json
{
  "context": "小天文喵是谁做出来的？",

  "initialAttention": {
    "alias:xiaotianwen_miao": 1.0
  },

  "relationContext": {
    "causal": 0.85,
    "similarity": 0.10,
    "opposition": 0.05,
    "causalDirection": "reverse"
  }
}
```

Expected qualitative behavior:

```text
t0:
小天文喵 dominant

early steps:
小天文 activates through SIMILARITY

then:
reverse CAUSAL path allows 小天文 → longz

longz should obtain a clear advantage over:
流星雨
天文观测
华理天文社社娘
```

Do NOT encode `created_by` as an engine relation.

---

# 32. Required B1 acceptance assertion

Do not require a fragile exact numeric value.

At some step before `maxSteps`:

```ts
attention['person:longz']
>
attention['concept:meteor_shower']

attention['person:longz']
>
attention['activity:astronomy_observation']

attention['person:longz']
>
attention['role:astronomy_club_mascot']
```

Prefer a stronger ratio assertion if stable:

```text
longz attention
>= 1.5 × max(unrelated similarity branches)
```

But do not tune the engine only to hit this ratio.

The main requirement is that relation context causes focused causal recall.

---

# 33. Required tests — relation semantics

Add unit tests.

## A. Similarity is symmetric

Stored:

```text
A --SIMILARITY--> B
```

must permit flow:

```text
A → B
B → A
```

without duplicate stored edges.

---

## B. Opposition is symmetric

Same requirement.

---

## C. Causal forward

Stored:

```text
A --CAUSAL--> B
```

with:

```text
causalDirection = forward
```

must allow:

```text
A → B
```

not:

```text
B → A
```

---

## D. Causal reverse

With:

```text
causalDirection = reverse
```

must allow:

```text
B → A
```

not:

```text
A → B
```

---

## E. Causal both

Both traversal directions are available.

---

# 34. Required tests — context gating

Use the same graph twice.

Case 1:

```text
relationContext:
causal = 0.85
similarity = 0.10
opposition = 0.05
```

Case 2:

```text
causal = 0.10
similarity = 0.85
opposition = 0.05
```

Verify the resulting edge flows differ in the expected direction.

The graph itself must not change.

---

# 35. Required tests — bounded outflow

Create:

```text
A with attention = 1.0
```

and many eligible outgoing edges.

With:

```text
maxOutflowFraction = 0.45
```

verify:

```text
total outgoing attention from A <= 0.45
retained attention at A >= 0.55
```

regardless of edge count.

---

# 36. Required test — hub degree robustness

Compare:

```text
Graph 1:
A has 2 eligible edges

Graph 2:
A has the same 2 edges
plus 50 additional eligible weak edges
```

The total amount leaving A must still be bounded by the same:

```text
maxOutflowFraction × A_attention
```

This test exists specifically to prevent hub leakage regression.

---

# 37. Required test — flow threshold is attention-dependent

Given one edge:

```text
associationStrength = 0.5
```

verify:

```text
high source Attention
→ flowPotential exceeds threshold
→ edge eligible

low source Attention
→ flowPotential below threshold
→ edge inactive
```

This preserves the original principle:

> more Attention enables a wider associative frontier.

---

# 38. Required test — multi-path convergence

Given:

```text
A → X
B → X
C → X
```

verify:

```text
incoming(X)
=
flow(A→X)
+
flow(B→X)
+
flow(C→X)
```

before the competition step.

Record this raw incoming value separately from final competed attention.

---

# 39. Required tests — competition

Given raw diffusion:

```text
A = 0.30
B = 0.10
C = 0.10
...
```

verify:

With:

```text
competitionGamma = 1
```

relative proportions are unchanged.

With:

```text
competitionGamma > 1
```

the ratio:

```text
A / B
```

increases.

---

# 40. Required test — total attention

Assert at both points:

```text
after raw local diffusion:
ΣD = 1

after competition:
ΣH = 1

after context reinjection:
ΣA_next = 1
```

Do not only test the final normalized output.

---

# 41. UI parameter panel changes

Current `App.tsx` exposes:

```text
temperature
selfRetention
contextAnchor
propagationFloor
emergenceThreshold
maxSteps
stepInterval
```

Change to:

```text
关联温度
temperature

流动潜力阈值
flowPotentialFloor

最大外流比例
maxOutflowFraction

竞争指数
competitionGamma

Context 回注
contextAnchor

涌现门槛
emergenceThreshold

扩散步数
maxSteps

播放间隔
stepInterval
```

Remove:

```text
selfRetention
propagationFloor
```

---

# 42. UI relation context panel

Add a visible panel near the selected case.

Show:

```text
当前关系 Context

因果       0.85
相似       0.10
对立       0.05

因果方向   逆向追溯
```

Use human-readable labels:

```text
forward → 顺因果
reverse → 逆因果追溯
both    → 双向
```

This should make it obvious why the same graph behaves differently under different current thoughts.

---

# 43. Optional relation context editing

If inexpensive, allow the user to edit:

```text
causal
similarity
opposition
causalDirection
```

in the UI and recompute the trace from t0.

If implemented:

- normalize the three weights after user change;
- display the normalized values;
- do not mutate the dataset file.

This is useful for the research demo but not required for acceptance if implementation time is limited.

---

# 44. Graph edge visualization

Encode the three relation types distinctly.

Suggested:

## CAUSAL

```text
directed arrow
```

Show traversal direction currently used:

- forward flow follows stored arrow;
- reverse flow visually travels against stored causal direction.

---

## SIMILARITY

Use a visually symmetric style.

For example:

```text
solid neutral line
```

No semantic arrow required in static display.

During actual flow, animate in the flow direction.

---

## OPPOSITION

Use:

```text
dashed / contrasting line
```

Again, flow animation shows current traversal direction.

Do not rely only on color.

---

# 45. Edge inspector changes

Current inspector shows:

```text
relation
association strength
transition share
attention carried
```

Replace with:

```text
relation type

stored source
stored target

traversal direction

association strength

relation gate

effective association

source attention

flow potential

flow threshold

eligible YES / NO

excess potential

actual attention carried
```

This distinction is crucial.

The UI should make it obvious that:

```text
static relationship
!=
current contextual conductivity
!=
actual flow
```

---

# 46. Node inspector changes

Add:

```text
held attention before step

eligible outgoing associations

requested outflow

outflow budget

actual outflow

retained attention
```

This is specifically needed to observe hub behavior.

Example:

```text
当前 Attention      0.3065
Eligible edges      3
Requested outflow   0.1210
Outflow budget      0.1379
Actual outflow      0.1210
Retained            0.1855
```

---

# 47. Competition visualization

For each step, preserve both:

```text
rawDiffusedAttention
finalAttention
```

Optionally expose:

```text
afterCompetitionAttention
```

Recommended `DiffusionStep` fields:

```ts
rawDiffusedAttention:
  Record<string, number>;

competedAttention:
  Record<string, number>;

attention:
  Record<string, number>;
```

Where:

```text
rawDiffusedAttention = D
competedAttention    = H
attention            = A_next after context anchor
```

This lets the inspector demonstrate what competition actually changed.

---

# 48. Timeline metrics

For each step show:

```text
Global Attention
Active Sources
Eligible Traversal Arcs
Actual Flowing Arcs
Currently Emerged
```

Also add:

```text
Attention concentration
```

Use a simple diagnostic such as:

```text
max node Attention
```

or optionally entropy:

\[
-\sum_i A_i\log A_i
\]

Do not make entropy part of the diffusion algorithm.

It is observation only.

---

# 49. Convergence visualization

Keep the existing:

```text
Incoming at tN
```

display.

Improve it to show relation type and traversal direction:

```text
小天文
CAUSAL · reverse
+0.083

另一路
SIMILARITY
+0.021
```

If multiple non-self paths feed the same node in one step:

```text
EMERGED BY CONVERGENCE
```

may continue to be displayed.

---

# 50. Dataset handling in App.tsx

Do not force the existing legacy `seed_graph.json` through the new validator.

For this revision:

1. add a new small explicit fixture:
   `src/data/three_relation_demo.json`
2. make the app load that fixture during implementation;
3. keep the old `seed_graph.json` as legacy/reference data if useful;
4. clearly mark in README that the full IRIS graph requires three-relation re-annotation before use.

Do not auto-convert the old data.

---

# 51. Minimum new demo dataset

`three_relation_demo.json` must include at least:

## B1 creator recall

```text
小天文喵
小天文
longz
流星雨
天文观测
华理天文社社娘
creator memory
```

and enough three-relation edges to demonstrate focused reverse-causal recall.

## Similarity/free association case

A case where:

```text
similarity
```

is dominant and multiple related concepts activate.

## Opposition case

A small case where opposition is dominant and the opposite/conflicting node becomes preferentially activated.

This ensures all three relation types visibly work.

---

# 52. Exact file changes expected

At minimum modify:

```text
src/types.ts
src/engine/diffusion.ts
src/engine/validation.ts
src/app/App.tsx
tests/diffusion.test.ts
tests/cases.test.ts
README.md
```

Add:

```text
src/data/three_relation_demo.json
```

You may split UI components if desired, but do not perform an unrelated UI rewrite.

---

# 53. Remove obsolete concepts

The codebase should no longer use these as model parameters:

```text
selfRetention
propagationFloor
```

The UI and README must not describe them as part of the current model.

The old fixed-transition `buildTransitions()` implementation must not remain in the simulation path.

---

# 54. Preserve current strengths

Do not regress:

- deterministic simulation;
- trace replay;
- step-by-step timeline;
- node inspector;
- edge inspector;
- global attention display;
- emergence tracking;
- incoming contribution visualization;
- expected target markers;
- trace export if already present.

---

# 55. No Top-K

Still strictly prohibited:

```text
fixed top K recalled nodes
fixed top K outgoing edges
winner-take-all memory selection
embedding retrieval
```

Competition is not Top-K.

All nodes remain in the Attention state.

The number of emerged nodes is not predetermined.

---

# 56. No LLM in P0.2

Do not add an LLM for Relation Context parsing yet.

RecallCase explicitly supplies:

```text
initialAttention
relationContext
```

Natural language `context` remains a human-readable description.

Future work may infer these automatically.

Not in this task.

---

# 57. No Dream / learning changes

Do not implement:

```text
Dream
automatic relation learning
association-strength updates
write-back
memory consolidation
identity merge
```

This revision is only the fast Recall dynamics and visualization.

---

# 58. Acceptance criteria

The modification is complete only if all of the following are true.

## A. Schema

Only:

```text
CAUSAL
SIMILARITY
OPPOSITION
```

are accepted as associative edge types.

---

## B. Relation Context

Each RecallCase has an explicit normalized relation context.

---

## C. Causal direction

Reverse causal traversal works without storing fake reverse causal edges.

---

## D. Attention-dependent eligibility

Edge eligibility depends on:

\[
A_i
S_{ij}^{1/T}
C_R[type]
\]

not on static edge rank.

---

## E. Bounded outflow

No node can send more than:

\[
maxOutflowFraction \times A_i
\]

per step.

---

## F. Multi-path convergence

All incoming path contributions add.

---

## G. Competition

`competitionGamma > 1` visibly sharpens the Attention distribution.

---

## H. Conservation

Attention remains 1 at:

```text
raw diffusion
competition output
final context-anchored state
```

within epsilon.

---

## I. B1 focus regression

For:

```text
“小天文喵是谁做出来的？”
```

the demo must no longer treat:

```text
longz
流星雨
天文观测
社娘身份
```

as roughly equivalent branches.

Under reverse-causal Context:

```text
longz / creator-related node
```

must gain a clear attention advantage over unrelated similarity branches.

---

## J. Inspectability

The UI exposes enough diagnostics to explain why an edge did or did not carry attention.

---

# 59. Test commands

Run:

```bash
npm test
npm run build
```

Both must pass.

Do not weaken tests simply to make the revision green.

---

# 60. Required final report

Return exactly this structure:

```text
STATE: EXECUTED

TASK:
Three-Relation Attention Dynamics P0.2

CHANGED_FILES:
...

SCHEMA:
relation types = CAUSAL / SIMILARITY / OPPOSITION

FORMULA:
relation-conditioned diffusion = implemented / not implemented
bounded outflow = implemented / not implemented
competition = implemented / not implemented
causal reverse traversal = implemented / not implemented

REMOVED:
selfRetention = yes/no
propagationFloor = yes/no
legacy fixed transition softmax = yes/no

B1_REGRESSION:
longz peak attention:
meteor peak attention:
observation peak attention:
mascot-role peak attention:
result:

TESTS:
...

BUILD:
...

LEGACY_DATA_AUTOMIGRATION:
NO

KNOWN_LIMITATIONS:
...

BLOCKERS:
NONE
or exact blocker
```

---

# 61. Core formula summary

The current P0.2 Recall dynamics are frozen as:

## Relation-conditioned association

\[
G_{ij}
=
S_{ij}^{1/T}
C_R[type(i,j)]
\]

## Attention-dependent flow potential

\[
Q_{ij}
=
A_iG_{ij}
\]

## Thresholded excess potential

\[
E_{ij}
=
\max(0,Q_{ij}-\theta_{flow})
\]

## Bounded node outflow

\[
O_i
=
\min
\left(
L_{\max}A_i,
\sum_jE_{ij}
\right)
\]

## Local flow

\[
F_{ij}
=
O_i
\frac{E_{ij}}
{\sum_kE_{ik}}
\]

## Retention

\[
F_{ii}
=
A_i-O_i
\]

## Multi-path convergence

\[
D_j
=
\sum_iF_{ij}
\]

## Global competition

\[
H_j
=
\frac{D_j^\gamma}
{\sum_kD_k^\gamma}
\]

## Context reinjection

\[
\boxed{
A_j(t+1)
=
(1-\lambda)H_j+\lambda C_j
}
\]

## Global invariant

\[
\boxed{
\sum_jA_j(t)=1
}
\]

---

# 62. One-sentence implementation principle

> **Association determines what can be recalled; Context determines which of the three relation channels is currently conductive; bounded outflow prevents hubs from leaking attention; convergence and competition determine what finally enters Working Memory.**

P0.2 ends here.
