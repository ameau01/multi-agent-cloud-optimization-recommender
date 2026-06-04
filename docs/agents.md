# Agents

Six agents across four roles: a Supervisor, a System Mapper, three Tier Specialists, and a Cross-Tier Evaluator. Each has a single clear job.

This doc covers what each agent does, what it does not do, and why it earns its place.

- The overview is in the [README](../README.md).
- The Topology and end-to-end flow are in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
- The harnesses each agent runs under are in [`harnesses.md`](harnesses.md).
- The decisions behind this agent set are in [`decisions.md`](decisions.md).

## 1. Supervisor

**Role** Orchestrates the optimization review workflow. The entry point of every review.

**Responsibilities**

- **Trigger handling** Accepts review requests — scheduled, change-driven, or on-demand. Validates the input is well-formed before any downstream agent runs.
- **Architecture model retrieval** Invokes the System Mapper to obtain the tier graph and analysis plan.
- **Specialist invocation** From the analysis plan, decides which Tier Specialists to invoke. Skips specialists for tiers not in the topology.
- **Low-confidence handling** _(design intent; not yet wired)._ When a specialist returns a finding below the confidence threshold, the Supervisor is the place where retry / pass-through-with-flag / defer-to-HITL decisions belong. The current Supervisor implementation has the routing surface for these branches but no confidence-driven branch is active yet; low-confidence findings flow straight through to the Cross-Tier Evaluator, which surfaces them in its drift-check.
- **Aggregation** Collects specialist findings and forwards them to the Cross-Tier Evaluator along with the cross-tier pairs of interest.

**Inputs** Review trigger metadata (target app + optional alert description). The Input Harness's validation verdict for the target scenario.
**Outputs** Specialist invocation commands. Aggregated findings package for the Evaluator.

**Why this is a separate agent** A pass-through router does not earn its own agent layer. This Supervisor earns its layer because it makes real workflow decisions: which subset of specialists fits this topology, how to handle low-confidence findings, when to escalate. State-machine routing alone could not make these without an LLM-driven layer above it.

The Supervisor's continual-monitoring story — deciding when applications are due for review based on time, recent changes, or anomalies — is design intent, scoped to scenario-batch invocation for the portfolio. See [`decisions.md`](decisions.md).

**What the Supervisor does not do** Analyze telemetry (the specialists' job). Synthesize recommendations (the Evaluator's job). Gate recommendations against the human reviewer (the Action Harness's job).

## 2. System Mapper

**Role** Translates an infrastructure description (Terraform) into an analysis plan the rest of the system reasons against.

**Responsibilities**

- **Terraform parsing** Extracts resources, attributes, and dependency relationships from Terraform stubs.
- **Tier classification** Maps parsed resources into compute, data layer (database, cache), and network tiers.
- **Dependency graph construction** Identifies which tiers communicate with which. Characterizes the connection type (synchronous query, read-through cache, async queue).
- **Analysis plan generation** Produces a structured plan specifying which specialists are required and which cross-tier pairs the Evaluator should attend to.

**Inputs** Terraform definition files. Sidecar metadata (for cross-referencing instance classes and counts).
**Outputs** A structured architecture model: list of tiers, list of inter-tier dependencies, analysis plan.

**Why this is a separate agent** The sidecar metadata already contains instance classes, counts, replica counts, pool sizes. A System Mapper that only read the sidecar would be a JSON deserializer. This agent earns its layer because it parses **how the tiers connect**, encoded in Terraform's `depends_on` and reference relationships, not in the sidecar's flat configuration.

The output is what makes the Supervisor's decisions meaningful. Without the analysis plan, the Supervisor would invoke all three specialists for every review regardless of topology.

Parsing uses `python-hcl2` (or equivalent). For the portfolio, Terraform stubs are hand-authored alongside each scenario. They live in the published dataset (`scenarios/NN/main.tf`) and are fetched at runtime by `src/data_loader.py`. See [README](../README.md) for the Quick Start data-loading section.

**What the System Mapper does not do**

- Validate Terraform syntax or correctness. That is not the system's job.
- Recommend architectural changes. It describes; it does not prescribe.
- Reason over telemetry. It reads only Terraform and the sidecar.

## 3. Tier Specialists (×3)

Three specialists run in parallel, each scoped to one tier: **Compute Analyst**, **Data Layer Analyst**, **Network Analyst**. They share an architectural pattern and differ only in the read surface they operate against.

**Role** Each specialist performs deep, tier-bounded analysis using ReAct reasoning against a constrained read surface. Produces a structured finding.

**Responsibilities**

- **ReAct loop** Form a hypothesis. Query the read surface. Observe. Refine. Conclude. **This ReAct loop is the foundation of the system's audit trail. A zero-shot approach was rejected because it acts as an unauditable black box; by contrast, the ReAct loop forces the specialist to bind every conclusion to a specific, logged tool observation.** Every cycle is logged to the audit trail.
- **Evidence-bound reasoning** Every conclusion cites the specific read operations that justified it. The Reasoning Harness enforces this structurally, see [harnesses.md](harnesses.md).
- **Confidence scoring** A specialist-level confidence combining evidence sufficiency and within-tier pattern strength.
- **Structured finding output** Produce a finding with an explicit `finding_type`, one of `issue_found`, `no_issue_found`, `diagnostic_deferral`, `insufficient_data`, plus the recommendation (if any), evidence references, and confidence.

**Inputs** Tier scope. Application context (SLA target, business context, current configuration). Access to the tier's read surface.
**Outputs** A structured specialist finding. Schema in [harnesses.md](harnesses.md).

### Why three specialists, not one

Cloud optimization is genuinely three different disciplines:

- **Compute** reasoning works against CPU/memory utilization patterns, scaling policy effectiveness, load balancer fairness, application-level latency.
- **Data layer** reasoning works against query performance, connection management, replication topology, cache coherence.
- **Network** reasoning works against inter-service latency, error rates, topology choices.

The optimization vocabularies, failure signatures, and appropriate interventions are different. A single agent forced to reason across all three would either over-generalize or skip depth in two of them.

Running them in parallel is a real architectural choice. It cuts wall-clock time, and it structurally prevents one specialist's reasoning from influencing another's. Specialist independence is what makes the Cross-Tier Evaluator's drift-check meaningful.

### The four-valued `finding_type`

A common failure mode of agent systems is producing a recommendation when the right answer is "no action." Specialists in this system are explicitly designed for four outcomes:

- **`issue_found`**, sufficient evidence supports a specific recommendation.
- **`no_issue_found`**, the tier is operating within expected ranges. A valid, full-confidence finding.
- **`diagnostic_deferral`**, within-tier data is too thin to call confidently — the right next step is more diagnosis (often a distributed trace), not a tier-level recommendation.
- **`insufficient_data`**, the required telemetry is missing or unreadable. Distinct from `diagnostic_deferral`: that one means the data is present but inconclusive; this one means the data wasn't there at all.

The Reasoning Harness enforces an evidence threshold before any `issue_found` can be produced. Without sufficient evidence, the specialist must produce one of the other three. This is what gives the system its **restraint capability**.

### The ReAct tool surface

Specialists reason against an MCP read surface, scoped per tier. Each specialist's MCP toolset contains only the operations for its own tier, so out-of-scope access is impossible at the tool layer — not merely discouraged. The partitioning below is enforced, not advisory.

Every operation is keyed on `app_name`, and the telemetry reads also take `tier` and `metric`. The tables below list operations and their tier scope; for full signatures see [`mcp-server.md`](mcp-server.md).

**Compute Analyst**

| Available operation         | Tier scope                     |
| --------------------------- | ------------------------------ |
| `get_time_series`           | compute                        |
| `get_summary_statistics`    | compute                        |
| `get_time_pattern`          | compute                        |
| `detect_threshold_breaches` | compute                        |
| `get_metric_distribution`   | compute                        |
| `get_business_context`      | (no tier)                      |
| `get_sla_target`            | (no tier)                      |
| `get_configuration`         | compute                        |
| `get_monthly_cost`          | (no tier)                      |
| `get_before_after_evidence` | (no tier)                      |
| `get_per_instance_breakout` | compute (Compute Analyst only) |

The Compute Analyst cannot invoke read operations against `database`, `network`, or `cache` tiers. The Action Harness rejects out-of-scope calls.

**Data Layer Analyst**

| Available operation         | Tier scope      |
| --------------------------- | --------------- |
| `get_time_series`           | database, cache |
| `get_summary_statistics`    | database, cache |
| `get_time_pattern`          | database, cache |
| `detect_threshold_breaches` | database, cache |
| `get_metric_distribution`   | database, cache |
| `get_business_context`      | (no tier)       |
| `get_sla_target`            | (no tier)       |
| `get_configuration`         | database, cache |
| `get_monthly_cost`          | (no tier)       |
| `get_top_queries`           | (no tier)       |
| `get_top_cache_keys`        | (no tier)       |
| `get_before_after_evidence` | (no tier)       |

The Data Layer Analyst covers both database and cache tiers, because cache behavior is most meaningfully analyzed in relation to database load.

**Network Analyst**

| Available operation         | Tier scope |
| --------------------------- | ---------- |
| `get_time_series`           | network    |
| `get_summary_statistics`    | network    |
| `get_time_pattern`          | network    |
| `detect_threshold_breaches` | network    |
| `get_metric_distribution`   | network    |
| `get_business_context`      | (no tier)  |
| `get_sla_target`            | (no tier)  |
| `get_configuration`         | network    |
| `get_monthly_cost`          | (no tier)  |
| `get_before_after_evidence` | (no tier)  |

### Why structural scoping matters

A specialist **cannot** conclude something based on evidence it was structurally prevented from accessing. The audit trail records every tool call. The Action Harness rejects out-of-scope calls before they happen. A Compute Analyst that wanted to peek at database connection counts simply cannot, the call is rejected and logged as a violation.

This is what makes specialist independence a real property. Three specialists with no access to each other's data cannot have correlated within the analysis. When the Evaluator then synthesizes across them, the cross-tier interactions it identifies are genuine emergent properties, not artifacts of contamination.

It also makes audit-trail interpretation honest. A reviewer reading the trail sees exactly what each agent saw. There is no "the specialist may have considered X" ambiguity.

### A worked ReAct cycle

```
Thought: Is CPU utilization chronically below healthy ranges?
Action:  get_summary_statistics(app_name='app-01', tier='compute', metric='cpu_p95', window='full')
Observation: {p50: 18.4, p90: 24.7, p95: 27.1, mean: 19.2, ...}

Thought: Below healthy compute baseline (40, 60% p50). Check if consistent.
Action:  get_time_pattern(app_name='app-01', tier='compute', metric='cpu_p50', granularity='hour')
Observation: {pattern: 'flat', weekday_vs_weekend_ratio: 1.02, ...}

Thought: Flat low. Need current configuration.
Action:  get_configuration(app_name='app-01', tier='compute')
Observation: {instance_class: 't3.large', instance_count: 8, scaling_policy: 'none'}

Thought: Recommend downsize. Need before/after evidence to ground the change.
Action:  get_before_after_evidence(app_name='app-01')
Observation: {config: 't3.large × 8 fixed', change: 't3.medium × 4 fixed',
       outcome: 'CPU p50 stayed 12-22%, SLA preserved'}

Finding: issue_found, recommendation: "Switch t3.large → t3.medium and reduce 8 → 4 replicas",
     with evidence refs to all four observations above.
```

Every observation in this loop is logged to the audit trail.

### What specialists do not do

- Access other tiers' data. The tool surface is structurally scoped.
- Synthesize across tiers. That is the Evaluator's job.
- Gate their own output. That is the Action Harness's job.

## 4. Cross-Tier Evaluator

**Role** The synthesis layer and the system's primary quality gate against single-specialist drift. **Crucially, the Evaluator is a synthesis engine, not a "winner-picker." It does not simply vote on or select the best specialist finding; rather, it looks for correlated cross-tier drift that individual specialists cannot see.** The architectural keystone, without it, three specialists produce three findings with no mechanism to reconcile them.

**Responsibilities** Three sub-steps, in sequence.

**Step 1, Drift-check each specialist**

For each specialist finding, the Evaluator examines:

- Does the recommendation follow from the cited evidence?
- Is the evidence-binding tight, or does the recommendation reach beyond what the evidence supports?
- Are there internal contradictions within the specialist's reasoning trace?

Drift-check verdicts are logged to the audit trail per specialist. A specialist whose finding fails drift-check has its weight in synthesis reduced, and the failure is surfaced in the review packet so the human reviewer sees it.

**Step 2, Identify cross-tier interactions**

Using the cross-tier pairs of interest from the analysis plan, the Evaluator examines:

- Which findings **conflict** directly (e.g., Compute recommends downsize while Data Layer evidence shows the database is the bottleneck)?
- Which findings **compound** (e.g., a cache miss cascade implicates both cache and database tiers, requiring a coordinated recommendation)?
- Which findings **depend** on each other (e.g., fixing the data layer first changes what the compute recommendation should be)?

**Step 3, Synthesize a balanced recommendation**

With drift-checked findings and identified interactions, the Evaluator produces:

- A final recommendation that balances cost, performance, and reliability dimensions explicitly.
- Trade-off scores across the three dimensions (each on its own scale, with the trade-off articulated rather than collapsed into a single number).
- An evaluator-level confidence score combining specialist confidences with cross-tier consistency and trade-off resolution clarity. See [harnesses.md](harnesses.md).
- A reasoning trace citing which specialist evidence supported the synthesis.

**Inputs** Aggregated specialist findings (1 to 3). Cross-tier pairs of interest from the analysis plan. Application context.
**Outputs** A synthesized recommendation with balanced action, trade-off scores, evaluator confidence, drift-check verdicts per specialist, and per-specialist contribution traces. This is the input to the Action Harness's recommendation gate.

### LLM-as-judge, judge of what

The Evaluator uses LLM-as-judge in two senses:

- **Judge of specialist reasoning quality** (Step 1), assessing whether each specialist's recommendation follows from its cited evidence.
- **Judge of trade-offs** (Step 3), weighing cost vs. performance vs. reliability when they point in different directions.

Both are real judging jobs. The Evaluator's synthesis and the specialists' ReAct telemetry analysis both warrant a capable model; see [decisions.md](decisions.md) for model configuration.

### Diagnostic deferral

For scenarios where capacity metrics are normal but latency is elevated across tiers simultaneously, the Evaluator's recommendation can carry `finding_type: diagnostic_deferral` rather than a balanced action. This is the system's **diagnostic-deferral capability** — recognizing when the right next step is a distributed trace analysis to identify root cause, not a scaling decision.

The same `finding_type` is available to individual specialists when within-tier data is too thin to call confidently, so the deferral signal can originate at the tier level (when one specialist sees inconclusive data) or at the synthesis level (when the Evaluator reconciles three healthy-looking findings against an SLA-violating reality). The Action Harness's recommendation gate accepts all four `finding_type` values as legitimate terminal outputs; `diagnostic_deferral` is not a failure mode.

### What the Evaluator does not do

- Catch correlated multi-specialist drift. If all three drift the same way with no internal conflict, the Evaluator has no signal. HITL catches this, supported by the audit trail.
- Act on its own recommendation. The recommendation passes through the Action Harness gate into HITL.
- Override the System Mapper's analysis plan. Cross-tier pairs of interest are input, not chosen.

## Why this specific agent set

The architecture was settled by asking, for each candidate agent, whether removing it would leave the system meaningfully worse:

| Agent                     | Architectural Cost of Removal                                                                                                                      |
| :------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Supervisor**            | Removes dynamic orchestration. All specialists would execute blindly regardless of actual topology, and low-confidence retry logic would be lost.  |
| **System Mapper**         | Destroys the structural baseline. The Supervisor would lose its routing logic, and cross-tier dependencies would require brittle hardcoding.       |
| **Tier Specialists (x3)** | Forces a single generalized agent across all domains, guaranteeing shallow analysis and the collapse of tier-specific, high-fidelity audit trails. |
| **Cross-Tier Evaluator**  | Strands the system with isolated, potentially conflicting findings. Eliminates the drift-check, trade-off scoring, and final synthesis.            |

Each agent earns its place. None is decorative.
