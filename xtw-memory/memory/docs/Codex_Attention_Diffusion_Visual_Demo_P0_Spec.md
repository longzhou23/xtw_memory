# Codex Development Spec — Associative Memory Attention Diffusion Visual Demo P0

**Project:** 小天文 Memory  
**Task:** Attention Diffusion / Memory Emergence Visual Demo P0  
**Scope:** Demo only — not production Memory  
**Developer:** Codex  
**Dataset / Annotation:** provided separately by ChatGPT after this spec is frozen  
**Status:** IMPLEMENTATION SPEC

---

# 0. Purpose

Build a local, interactive visual demo for the current Memory research hypothesis:

> Long-term memory recall is modeled as a redistribution of a finite global attention state over a heterogeneous associative memory network. Memories are not selected by fixed Top-K retrieval; they emerge when attention reaches them through context-driven diffusion, competition, and multi-path convergence.

The demo must make this process visible.

The primary research question is:

> Can a fixed amount of global attention diffuse through an associative memory graph such that relevant memories naturally emerge, especially when multiple weak paths converge on the same node?

This is a **research visualization prototype**, not a production memory system.

---

# 1. Core Design Principles

The implementation must preserve the following concepts.

## 1.1 Heterogeneous Nodes

A graph node is not restricted to “fact” or “episode”.

Any cognitive object may be represented as a node, for example:

- Person
- Alias
- Self
- Memory
- Episode
- Concept
- Activity
- Location
- Object
- Goal
- Trait
- Role
- Question
- Procedure
- other future types

The diffusion engine must not contain special-case logic that assumes only one or two node types.

All node types share one common property in the associative layer:

> they can receive attention.

---

## 1.2 Association Is Separate From Attention

Each edge has a persistent association value:

```text
association_strength
```

This is a long-lived property of the memory graph.

Each node has a transient value:

```text
attention
```

This exists only for the current recall simulation.

Do not mix these meanings.

---

## 1.3 Fixed Global Attention

At each simulation step:

```text
Σ node.attention = TOTAL_ATTENTION
```

For P0:

```text
TOTAL_ATTENTION = 1.0
```

Allow a small floating-point tolerance.

The graph may contain many nodes, but the total available attention remains fixed.

---

## 1.4 Recall Is Diffusion, Not Top-K Search

Do not implement recall as:

```text
query
→ similarity sort
→ top_k
```

The demo must instead show:

```text
Context
→ initial seed attention
→ iterative redistribution
→ convergence / competition
→ emergence
```

A fixed Top-K may be used only for UI display convenience if necessary, never as the recall algorithm.

---

## 1.5 Multi-Path Convergence

If several active paths lead to the same node, their incoming attention must accumulate.

Example:

```text
A ──weak──► X
B ──weak──► X
C ──weak──► X
```

Each path alone may be insufficient.

Together:

```text
incoming(X)
=
incoming_from_A
+
incoming_from_B
+
incoming_from_C
```

The demo must visibly support cases where X emerges only because several paths converge.

This is one of the most important P0 behaviors.

---

## 1.6 Emergence Is Not Truth

A node becoming `EMERGED` means:

> this cognitive object has become sufficiently active to enter the current Working Memory.

It does **not** mean:

- the statement is objectively true;
- identity has been canonicalized;
- all connected facts should be copied;
- the node should be written back into long-term memory.

The P0 demo is read-path only.

---

# 2. Responsibility Boundary

## 2.1 ChatGPT / Annotation Side

A separate annotated dataset will be provided containing:

- nodes
- edges
- association priors
- test cases
- seed nodes / initial context distribution
- expected emergence nodes
- distractors
- source IRIS memory IDs where applicable

These annotations define the research cases.

---

## 2.2 Codex Side

Codex must implement:

- graph loading;
- diffusion engine;
- visualization;
- simulation controls;
- inspectors;
- metrics / traces;
- test infrastructure.

Codex must **not**:

- invent new memory facts;
- change the meaning of annotated nodes;
- merge aliases automatically;
- infer identity;
- invent missing edges;
- alter annotation weights to make a case pass;
- call an LLM to repair test data.

If an annotated case does not behave as expected under the implemented dynamics, report the behavior rather than silently changing the dataset.

---

# 3. Technology

Preferred stack:

```text
Vite
React
TypeScript
Cytoscape.js
```

Use the existing repository conventions if this demo is added to an existing project.

No backend is required.

No database is required.

No external API is required.

The demo must work fully offline after dependencies are installed.

---

# 4. Suggested Project Structure

Example only; adapt to repository conventions if necessary.

```text
src/
  app/
    App.tsx

  memory-demo/
    types.ts
    data/
      seed_graph.json
    engine/
      diffusion.ts
      transition.ts
      metrics.ts
    components/
      CasePanel.tsx
      GraphView.tsx
      NodeInspector.tsx
      EdgeInspector.tsx
      SimulationControls.tsx
      Timeline.tsx
      EmergencePanel.tsx
      AttentionSummary.tsx
    state/
      useSimulation.ts

tests/
  diffusion.test.ts
  cases.test.ts
```

Keep the diffusion engine independent from React.

It must be possible to unit-test the engine without rendering the UI.

---

# 5. Data Contract

The final annotation file will be supplied separately.

Codex should implement support for a schema equivalent to the following.

## 5.1 Graph Node

```ts
export type NodeType = string;

export interface MemoryNode {
  id: string;
  type: NodeType;
  label: string;

  sourceMemoryIds?: string[];

  metadata?: Record<string, unknown>;
}
```

Important:

```text
type
```

must remain open-ended.

Do not hard-code an exhaustive enum that prevents future node types.

---

## 5.2 Graph Edge

```ts
export interface MemoryEdge {
  id: string;

  source: string;
  target: string;

  relation: string;

  associationStrength: number;

  evidence?: string[];
  metadata?: Record<string, unknown>;
}
```

For the first annotated dataset:

```text
0 <= associationStrength <= 1
```

Treat it as a relative association prior for the demo.

It is not a calibrated probability.

---

## 5.3 Recall Case

```ts
export interface RecallCase {
  id: string;
  title: string;
  description?: string;

  context: string;

  initialAttention: Record<string, number>;

  expectedEmergence: string[];

  distractors?: string[];

  tags?: string[];
}
```

Require:

```text
Σ initialAttention ≈ 1.0
```

The annotation side will explicitly provide the initial seed distribution.

P0 does **not** need to parse natural-language context into seed nodes.

The `context` field is displayed for humans only.

---

## 5.4 Demo Dataset

```ts
export interface DemoDataset {
  version: string;

  nodes: MemoryNode[];
  edges: MemoryEdge[];
  cases: RecallCase[];
}
```

---

# 6. Diffusion Model P0

This is a deliberately minimal baseline.

Do not add cognitive mechanisms that are not listed here.

---

## 6.1 State

For N graph nodes:

```text
A_t ∈ R^N
```

where:

```text
A_t[i] >= 0
```

and:

```text
Σ A_t[i] = 1
```

`A_t[i]` is the attention held by node i at simulation step t.

---

## 6.2 Initial State

For the selected Recall Case:

```text
A_0 = case.initialAttention
```

All unspecified nodes start at 0.

Normalize once if floating-point input differs slightly from 1.

Do not create semantic seeds automatically.

---

## 6.3 Local Transition Weights

For each source node i, consider:

- its outgoing graph edges;
- a self-retention transition.

The engine must create a local transition distribution.

For each graph edge:

```text
logit(i→j)
=
associationStrength(i,j) / temperature
```

A self-retention option must exist:

```text
i → i
```

controlled by:

```text
selfRetention
```

The exact implementation may use one of these equivalent approaches:

1. include self-retention as another softmax logit; or
2. reserve `selfRetention` fraction first, then normalize the remaining outgoing fraction.

Choose one clean implementation and document it.

The default P0 behavior should be easy to understand and deterministic.

---

## 6.4 Sparse Propagation

Do not iterate over all graph nodes when unnecessary.

At each step, only process nodes where:

```text
attention >= propagationFloor
```

Nodes below the floor still retain their current state representation if needed, but do not expand outgoing transitions.

This is important because the long-term architecture assumes:

> conceptually global attention, computationally sparse local diffusion.

---

## 6.5 Multi-Path Accumulation

All incoming contributions to a target node must be summed before producing the next state.

Pseudo-code:

```text
next[target] += contribution(source1 → target)
next[target] += contribution(source2 → target)
next[target] += contribution(source3 → target)
```

Never keep only the strongest incoming path.

---

## 6.6 Context Anchoring

Pure diffusion may drift away from the original thought.

Use an optional context reinjection parameter:

```text
contextAnchor ∈ [0,1]
```

Let:

```text
C = A_0
```

After graph propagation produces `D_t`:

```text
A_(t+1)
=
(1 - contextAnchor) * D_t
+
contextAnchor * C
```

Then normalize for floating-point safety.

Interpretation:

```text
contextAnchor = 0
→ pure associative diffusion

contextAnchor > 0
→ current context continuously pulls attention back toward the original thought
```

Default should be modest, not dominant.

Suggested initial default:

```text
contextAnchor = 0.15
```

This is a demo parameter, not a research conclusion.

---

## 6.7 Global Attention Conservation

After every simulation step:

```text
abs(sum(A) - 1.0) <= epsilon
```

The engine should expose the current total attention so the UI can display it.

If conservation fails beyond floating-point tolerance, treat it as an implementation bug.

---

# 7. Emergence Model

A node is considered currently emerged when:

```text
attention >= emergenceThreshold
```

Suggested initial default:

```text
emergenceThreshold = 0.10
```

This value must be adjustable in the UI.

Also track:

```text
firstEmergedAtStep
peakAttention
currentAttention
```

Do not remove a node from the graph if its attention later drops.

For P0, it is useful to distinguish:

```text
currently emerged
```

from:

```text
has ever emerged during this run
```

Display both if practical.

---

# 8. Simulation Parameters

Expose these controls:

```text
temperature
selfRetention
contextAnchor
propagationFloor
emergenceThreshold
maxSteps
stepInterval
```

Suggested defaults:

```text
temperature        = 1.0
selfRetention      = 0.35
contextAnchor      = 0.15
propagationFloor   = 0.005
emergenceThreshold = 0.10
maxSteps           = 12
stepInterval       = 600ms
```

These are only starting values.

Do not describe them in code comments or UI as scientifically validated constants.

---

# 9. Visualization Requirements

The graph is the core of the demo.

## 9.1 Node Encoding

Node appearance should encode:

```text
Node Type
Current Attention
Emergence State
```

Recommended:

- shape or base style → node type;
- size → current attention;
- opacity / glow / border → activation and emergence.

Do not rely only on color.

The demo should remain interpretable even when several types are present.

---

## 9.2 Attention Visualization

A viewer should be able to tell at a glance:

> Where is the attention currently concentrated?

Node size should scale nonlinearly enough that differences are visible.

Do not make low-attention nodes disappear completely by default.

---

## 9.3 Emerged Nodes

A node above the threshold should receive a highly visible state:

```text
EMERGED
```

For example:

- outer ring;
- glow;
- badge;
- stronger border.

The user should not need to read numeric values to notice emergence.

---

## 9.4 Edge Visualization

Edges should display:

- relation label;
- association strength on inspection;
- attention flow during the current transition.

When stepping from t to t+1, highlight edges that carried attention.

The visual strength of the flow should correspond to:

```text
actual attention contribution
```

not merely static association strength.

This is important.

The user must be able to distinguish:

```text
“this relationship is strong”
```

from:

```text
“attention is actually flowing through it right now”
```

---

# 10. Main UI Layout

Recommended desktop layout:

```text
┌──────────────────────────────────────────────────────────────┐
│ Header / research hypothesis / selected case                │
├──────────────┬───────────────────────────────┬───────────────┤
│ Case Panel   │                               │ Inspector     │
│              │          Graph View           │               │
│              │                               │               │
├──────────────┴───────────────────────────────┴───────────────┤
│ Timeline / Controls / Attention Summary / Emerged Memories  │
└──────────────────────────────────────────────────────────────┘
```

Responsive layout is welcome, but desktop research use is the priority.

---

# 11. Case Panel

Display:

- case title;
- context;
- tags;
- initial seeds;
- expected emergence;
- distractors.

Controls:

```text
Load Case
Reset
```

Expected emergence should be shown as an annotation target, not hidden like a benchmark answer.

This is a research/debug demo.

---

# 12. Graph Inspector

When clicking a node, show:

```text
id
type
label
current attention
initial attention
peak attention
first emerged step
currently emerged
ever emerged
incoming attention this step
outgoing attention this step
source IRIS memory IDs
metadata
```

When clicking an edge, show:

```text
source
target
relation
association strength
transition share
actual attention carried this step
```

---

# 13. Simulation Controls

Must include:

```text
Run
Pause
Step
Reset
```

Also:

```text
Jump to t0
Previous Step
Next Step
```

if the trace has already been generated.

Allow playback speed adjustment.

---

# 14. Timeline / Trace

Store every state:

```text
A_0
A_1
A_2
...
A_t
```

The user must be able to scrub or click through previous steps.

For each step show at least:

```text
step index
total attention
number of active nodes
number of currently emerged nodes
top attention nodes
```

Again, `top attention nodes` is visualization only, not the retrieval algorithm.

---

# 15. Multi-Path Convergence Visualization

This deserves explicit support.

If one target node receives attention from multiple sources in the same step, the UI should make that visible.

For example, the node inspector may show:

```text
Incoming at t=3:

NICEICK       +0.041
Project Sekai +0.036
星乃一歌       +0.052
-------------------
Total         +0.129
```

If this pushes the node over the emergence threshold, visually annotate:

```text
EMERGED BY CONVERGENCE
```

This can be a debug label rather than a permanent taxonomy.

---

# 16. Attention Conservation Display

Always show:

```text
Global Attention = 1.000000
```

or equivalent.

If deviation exceeds tolerance, show an obvious warning.

This is a central invariant of the demo.

---

# 17. Metrics

For a selected annotated Recall Case, calculate:

```text
expected_emergence_hit_count
expected_emergence_total

distractor_emergence_count

first_emergence_step per expected node
peak_attention per expected node
```

Do not collapse this into one “accuracy score” yet.

We are observing dynamics, not optimizing a benchmark metric.

---

# 18. Required Test Cases

The annotation dataset will provide exact node IDs and graph contents.

The demo must support at least these semantic scenarios:

## Case A — Alias Bridge

A nickname/alias activates another name/person area without hard canonical merge.

Goal:

```text
alias
→ associated identity representation
→ related memories
```

---

## Case B — Multi-Path Convergence

Several seed paths independently point toward the same memory.

Goal:

```text
weak path A
+
weak path B
+
weak path C
→ memory emerges
```

This is the highest-priority P0 demonstration.

---

## Case C — Heterogeneous Multi-Hop

Example pattern:

```text
Person
→ Object
→ Activity
→ Concept
```

All types must share the same attention mechanism.

---

## Case D — Shared Context Without Identity Collapse

Example:

```text
Person A → Location X
Person B → Location X
```

Activating X may surface both people.

The engine must not infer:

```text
Person A == Person B
```

---

## Case E — Strong Direct Association

A simple one-hop positive control.

If the engine fails this, the diffusion implementation is invalid.

---

## Case F — Context Competition

One highly connected person may have several strong interests.

The selected contextual seeds should change which branch receives enough attention to emerge.

---

# 19. Unit Tests

At minimum test:

## 19.1 Attention Conservation

For every step:

```text
Σ attention ≈ 1
```

---

## 19.2 Determinism

Given:

```text
same graph
same parameters
same initial attention
```

the full trace must be identical.

No randomness in P0 diffusion.

---

## 19.3 Multi-Path Addition

If two sources contribute to X:

```text
incoming(X)
=
contribution1 + contribution2
```

Verify numerically.

---

## 19.4 Context Anchor

Verify that a non-zero `contextAnchor` reinjects the original seed distribution.

---

## 19.5 Propagation Floor

Nodes below the propagation floor must not expand their outgoing frontier.

---

## 19.6 Heterogeneous Types

The engine should produce identical numerical behavior regardless of node type labels.

Node type is presentation / semantic metadata, not a diffusion exception.

---

## 19.7 No Top-K Behavior

Create a graph where more than K nodes exceed emergence threshold.

Verify the engine allows all of them to emerge.

There must be no hidden fixed retrieval count.

---

# 20. Integration Tests

After the annotated IRIS seed graph is supplied, add integration tests for at least:

```text
one direct recall case
one alias case
one multi-path convergence case
one shared-context / anti-collapse case
```

Do not modify annotation data to make tests pass.

If a case fails:

```text
REPORT THE FAILURE
```

before changing diffusion semantics.

---

# 21. Performance Expectations

P0 graph size:

```text
~30–100 nodes
```

The implementation should comfortably handle this interactively.

However, structure the engine so that later graphs can grow larger.

Important architectural rule:

> Conceptually global attention, computationally sparse active frontier.

Avoid unnecessary full-graph loops where easy to avoid.

Do not prematurely optimize for millions of nodes.

---

# 22. Explicit Non-Goals

Do NOT implement:

```text
LLM calls
Embedding search
Vector database
Top-K retrieval engine
Dream consolidation
Automatic entity resolution
Canonical ID merge
Automatic graph extraction
Automatic association learning
Production persistence
IRIS migration
Memory writing
Episode Router
Episode Lifecycle
Reconciliation
Large-scale benchmark
```

The demo starts from a manually annotated graph.

---

# 23. UI Tone

This is a research instrument, not a consumer chatbot UI.

Prefer:

```text
clear
technical
observable
inspectable
minimal
```

over decorative visual effects.

The graph animation may be visually attractive, but it must never hide the numerical state.

Every visible effect should correspond to an actual simulation value.

---

# 24. README

Document:

```text
What the demo tests
What it does not claim
How the diffusion model works
Meaning of attention
Meaning of association strength
Meaning of emergence
How to load a dataset
How to add a recall case
How to run tests
```

Include the invariant:

```text
Σ attention = 1
```

and state clearly:

> Association strength is not attention, and emergence is not truth.

---

# 25. Deliverables

Codex should deliver:

```text
1. Runnable local React/Vite demo
2. Standalone diffusion engine
3. Dataset loader / validation
4. Graph visualization
5. Simulation controls
6. Timeline / trace inspection
7. Node and edge inspectors
8. Emergence visualization
9. Multi-path convergence visualization
10. Unit tests
11. Integration tests using provided annotation data
12. README
```

---

# 26. Dataset Validation

On load, validate:

```text
node IDs unique
edge IDs unique
all edge endpoints exist
all case seed nodes exist
all expected emergence nodes exist
all distractor nodes exist
associationStrength finite and >= 0
initial attention finite and >= 0
initial attention sum > 0
```

Normalize case initial attention to 1 only for minor floating point / authoring differences.

For major invalid data, fail loudly.

---

# 27. Research Trace Export

Add a simple export button if inexpensive.

Export the current run as JSON:

```json
{
  "caseId": "...",
  "parameters": {},
  "steps": [
    {
      "step": 0,
      "attention": {},
      "emerged": []
    }
  ]
}
```

This will later be useful for benchmark analysis.

Do not build a complex experiment database.

---

# 28. Acceptance Criteria

The task is considered complete when:

### A. The demo runs locally.

### B. A manually annotated heterogeneous graph can be loaded.

### C. A selected Recall Case initializes a fixed total attention state.

### D. Pressing `Step` visibly redistributes attention.

### E. Total attention remains conserved at every step.

### F. Different node types participate in the same diffusion engine.

### G. Attention arriving through several paths accumulates on the same node.

### H. At least one annotated Memory node can cross the emergence threshold because of multi-path convergence.

### I. No fixed Top-K is used to decide recall.

### J. The full attention trace can be inspected step by step.

---

# 29. Report Format

After implementation, return:

```text
STATE: EXECUTED

TASK:
Associative Memory Attention Diffusion Visual Demo P0

IMPLEMENTED:
...

ARCHITECTURE:
...

DIFFUSION_MODEL:
...

DATASET:
...

TESTS:
...

KNOWN_LIMITATIONS:
...

ANNOTATION_ASSUMPTIONS:
NONE
or list exact assumptions

PRODUCTION_MEMORY_CHANGES:
NONE

LLM_INTEGRATION:
NONE

TOP_K_RETRIEVAL:
NONE

READY_FOR_ANNOTATED_IRIS_DATA:
YES / NO
```

If annotated data has already been supplied and integrated, instead report:

```text
ANNOTATED_IRIS_DATA_INTEGRATED:
YES
```

---

# 30. Core Rule

This demo exists to test one idea:

> **Do relevant memories appear because finite attention diffuses and converges through the associative graph?**

Do not turn the task into a general memory platform.

Do not “improve” the research hypothesis.

Make the mechanism visible, deterministic, inspectable, and easy to modify.

---

# 31. Frozen Conceptual Model for P0

```text
                    CURRENT CONTEXT
                          │
                          ▼
                  Initial Attention C
                     Σ Attention = 1
                          │
                          ▼
          ┌──────────────────────────────┐
          │ Heterogeneous Memory Network │
          │                              │
          │ Person                       │
          │ Alias                        │
          │ Memory                       │
          │ Concept                      │
          │ Episode                      │
          │ Goal                         │
          │ Object                       │
          │ Location                     │
          │ ...                          │
          └──────────────────────────────┘
                          │
                 Association Strength
                          │
                          ▼
                 Sparse Local Diffusion
                          │
            ┌─────────────┴─────────────┐
            │                           │
       Competition                 Convergence
            │                           │
            └─────────────┬─────────────┘
                          ▼
                   Attention State
                     Σ Attention = 1
                          │
                          ▼
                Emergence Threshold
                          │
                          ▼
                   WORKING MEMORY
```

P0 ends here.
