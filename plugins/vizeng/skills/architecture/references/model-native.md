# Model-native architecture

Thesis: models benefit from abstractions more than humans do.
A human reading code can skim, glance at a file tree, and hold an informal picture.
A model pays for every token it reads and reasons best over short, explicit, consistent statements.
So an abstraction is good for a model when its *card* - a few lines of text - lets the model predict the code's behavior, safety and blast radius without reading the code.

The diagram exists for the human to see and edit the design.
The cards, names, roles and relationship verbs exist for the model.
Where the two pull in different directions, optimize the text for the model and let the diagram be the human's view of it.

## What changes versus traditional design

Traditional guidance optimizes for a human reader. Several tradeoffs flip for a model reader:

| Traditional instinct | Model-native choice | Why |
| --- | --- | --- |
| Short, elegant names | Long, literal, unique names (`FilingDedupGate`) | A name is a retrieval key; grep must return one thing, and the name must predict behavior. |
| Don't repeat what code says | State the contract on the card, even if "obvious" | The card replaces reading code; redundancy is cheap, re-deriving is expensive. |
| Flexible indirection (registries, DI by string, plugins) | Explicit wiring in one composition root | Models cannot follow string dispatch or framework magic without reading everything. |
| Positive descriptions | Add a `never` list | Models over-generalize; negative space stops them adding logic in the wrong place. |
| Conventions known by the team | Conventions encoded as roles with fixed contracts | A role is a compressed, shared contract; implicit tribal knowledge costs a model full reads. |
| Many small classes | Few deep modules with narrow interfaces (Ousterhout) | The interface is what fits in context; pass-through layers add hops and no information. |

## The card

Every box or circle in a model-native diagram is an abstraction with a card. Target 60-150 tokens.
If you cannot write the card within budget, the abstraction is doing too much or has no clear purpose.

| Field | Content |
| --- | --- |
| `role` | One role from the table below. Required. |
| `purpose` | One sentence: why it exists, in domain words. |
| `owns` | State or data only it may write. Ownership is exclusive. |
| `does` | Verbs it performs. Each should be testable. |
| `never` | Things a reader might expect it to do but it must not. |
| `in` / `out` | Typed inputs and outputs, naming Contract types. |
| `effects` | Every side effect: network, disk, DB, clock, randomness, env. Empty for pure roles. |
| `fails` | Failure modes and how each surfaces (raise, return, retry, dead-letter). Silent failures are a design bug. |
| `invariants` | Rules that must hold, each pointing to its guard test when one exists. |
| `paths` | Source files. Required for existing code. |
| `tests` | Tests that guard this abstraction. |

Relationships go on edges, not in the card: the model view folds them in as `-> <rel> <Target> (<label>)`.

## Role vocabulary (closed set)

The role carries a default contract, so the card only states deviations. Do not invent roles; if nothing fits, the abstraction probably mixes two roles and should be split.

| Role | Default contract |
| --- | --- |
| Entry | Process boundary (CLI, HTTP handler, cron, queue consumer). Parses and validates input, delegates. No domain logic. |
| Source | Produces items from outside the system. Owns its cursor/checkpoint. Does not filter or transform beyond decoding. |
| Gate | Decides keep/drop/allow/deny. Pure: no effects, no mutation. Returns a decision with a reason. |
| Transform | Pure input -> output mapping. No effects. Deterministic for the same input. |
| Router | Chooses a destination for an item. Does not modify the item. |
| Orchestrator | Sequences other abstractions and owns control flow across them (ordering, retries, concurrency). Owns no domain rules. |
| Store | Sole owner of persistence for one aggregate. Nothing else touches its tables/files. |
| Adapter | Sole wrapper for one external system. Translates its errors and types into Contracts. Nothing else calls that system. |
| Policy | Rules and thresholds as data or pure functions. Read by Gates/Routers/Orchestrators. No effects. |
| Sink | Terminal output: publish, notify, emit. Owns delivery semantics (at-least-once, idempotency key). |
| Contract | Shared types/schemas crossing boundaries. Data only, no behavior. Changes are versioned. |

## Relationship vocabulary

Use one of: `calls`, `emits`, `reads`, `writes`, `owns`, `implements`, `guards`, `configures`.
Put what flows in the edge `label` (a Contract type name is ideal), in 1-4 words: the label is a retrieval key like a name, not prose. Conditions and schedules ("only high severity", "every 30s") go in the target's card.
Use `dotted` for optional, async or weak dependencies; `thick` for the primary data path.

## Naming rules

1. `<DomainNoun><RoleOrVerb>`: `FilingSource`, `TickerNormalizeTransform`, `AlertPublishSink`. The suffix may be the role or a more precise verb.
2. Unique in the repo: `grep -rw Name` returns only its definition and uses.
3. Banned as a whole name or suffix: Manager, Helper, Util(s), Service, Base, Handler, Processor, Common, Misc, Core. They predict nothing.
4. One name per concept across code, card, diagram, tests and logs. A rename is a migration: change all of them together.
5. Prefer the domain's literal term over a metaphor.

## Structural rules

- **One-hop rule**: any question about a behavior ("what happens when X arrives twice?") should be answerable from that abstraction's card plus at most one neighbor's card.
- **One composition root**: wiring happens in one Orchestrator or Entry. Dependencies are explicit constructor or function parameters.
- **Effects at the edge**: IO lives in Source, Store, Adapter, Sink. Gate, Transform, Router, Policy are pure. A pure-role card with effects is a violation.
- **Exclusive ownership**: each piece of state has exactly one owner card.
- **Flat data across boundaries**: pass Contracts (plain typed data), not objects with hidden behavior.
- **Deep over wide**: merge pass-through abstractions; split only when a card exceeds budget or needs two roles.

## Reverse-engineering an existing codebase

1. Inventory: entry points (main, CLI, routes, jobs), composition roots, packages, stores, external clients, shared schemas.
2. For each candidate abstraction, write the card from the code - real names, real paths, real tests. Note where the card had to say "also does X" (a role violation) or where effects hide inside a pure-looking module.
3. Draw current state first, all `current`, using the code's names even if they break the naming rules.
4. Run the checklist. Add each fix as a `proposed` node (new name, merged or split abstraction) with a dotted `implements` edge from the current node, or as a `note`. Do not overwrite the current map with the ideal one.

## Review checklist

Run this before calling a model-native diagram done, and report the results:

- Every box/circle has a role from the table and a `purpose`.
- Card size within budget; anything over is a split candidate.
- Pure roles declare no `effects`; every effect sits on a Source/Store/Adapter/Sink.
- Each state item has exactly one `owns`.
- Each external system has exactly one Adapter.
- `fails` names how every failure surfaces; nothing is swallowed.
- Names pass the naming rules and grep uniqueness (check with grep for existing code).
- Pick three realistic questions about behavior and count hops; any over one hop is a finding.
- Compression: for existing code, estimate card tokens versus the tokens of code it summarizes. A card that is not much shorter than its code is not earning its place.
