# System design methods

Recommend one primary method and at most one secondary lens. Tie the choice to the project's constraints in one paragraph.
Simon Brown's C4 levels are always the drawing discipline (context -> containers), whatever method drives the decisions.

| Method (practitioner) | Use when | Core moves | Diagram emphasis |
| --- | --- | --- | --- |
| Data-intensive design (Martin Kleppmann, *Designing Data-Intensive Applications*) | Data volume, consistency, replication or derived data dominate | State reliability/scalability/maintainability goals; pick system of record vs derived data; choose replication, partitioning and consistency per store; make dataflow explicit | Stores as first-class nodes, thick edges for the primary dataflow, derived-data pipelines |
| The log as the backbone (Jay Kreps, "The Log") | Many producers/consumers, event streams, replay, integration across services | Make an append-only log the source of truth; consumers derive state; idempotent replay | One central log, dotted edges for async consumption |
| Back-of-envelope sizing (Jeff Dean, "Numbers everyone should know") | Performance or cost is uncertain and decides the design | Estimate QPS, bytes, latency budgets per hop from known numbers before choosing components | Edge labels carry rates and sizes |
| Everything fails (Werner Vogels) | High availability, cloud services, operational risk | Assume every dependency fails; isolate blast radius (cells, bulkheads); timeouts, retries with backoff, idempotency, graceful degradation | Failure domains as grouped regions, notes on each dependency's failure behavior |
| Entities and idempotence (Pat Helland, "Life Beyond Distributed Transactions") | Distributed writes without global transactions, payments, orders | Partition by entity; at-least-once messaging with idempotent handlers; reconcile with activities | Entity owners, message edges labeled with idempotency keys |
| Strategic DDD (Eric Evans; Vaughn Vernon) | Complex business domain, multiple teams, ambiguous boundaries | Find bounded contexts and the ubiquitous language; map context relationships (anti-corruption layers, shared kernel) | One box per bounded context, labeled translation edges |
| Monolith first, split by evidence (Martin Fowler; Sam Newman on boundaries) | New product, small team, uncertain domain | Start as a modular monolith with hard internal boundaries; extract services only where scaling, deploy cadence or ownership demand it | Modules inside one deployable, proposed extractions dotted |
| Four-step framework (Alex Xu, *System Design Interview*) | Greenfield service with a clear functional ask; quick structured pass | Scope and requirements -> high-level design -> deep-dive the hardest two components -> bottlenecks and wrap-up | High-level containers, the deep-dived components detailed |
| Hints for system design (Butler Lampson) | Systems or infrastructure software; performance/fault-tolerance tradeoffs | Keep interfaces simple and stable; do one thing well; use hints and caching; end-to-end checks; plan to throw one away | Interfaces between subsystems, caches and checks annotated |
| Let it crash (Joe Armstrong, Erlang/OTP) | Long-running concurrent workers, many independent tasks | Isolate processes; supervisors restart on failure; no defensive error handling inside workers | Supervision tree of workers |

Secondary lenses that combine well: back-of-envelope sizing with anything; everything-fails with the log or data-intensive; strategic DDD with monolith-first.

When researching, look for: how two or three comparable systems are built, published postmortems in the domain, and the method author's own writing for the moves you plan to apply. Cite what you used in the document `technique.why` or a note.
