# Design Decisions and Trade-offs

This document explains the reasoning behind our architectural choices and the alternatives we rejected. While the README and ARCHITECTURE.md cover the “what” and the “why,” this document focuses on the “why not.” It is written for senior reviewers who want to understand the trade-offs we accepted.

Note: To avoid repetition, detailed implementation mechanisms are not explained here; instead, we link directly to the relevant component documentation.

## The constraints every decision answers

These are the three constraints from the README's [Three constraints, one architecture](../README.md#three-constraints-one-architecture) section, restated here as the rubric every decision below is judged against.

1. **Recommendations must be transparent.** Every claim is anchored in evidence, and the reasoning chain can be replayed forward or backward.
2. **The diagnosis must hold up across tiers** — because the cause often sits in a different tier than the symptom. Specialists analyze independently, then an evaluator reconciles them with the wider view.
3. **The system must never act on its own** — so it surfaces recommendations to a human and stops there. The Action Harness stays narrow.

Each decision addresses one or more of these constraints. The rejected alternatives aren't inherently wrong; they simply belong in environments with different requirements, such as high-throughput automation, single-tier diagnosis, or closed-loop systems.

## 1. Multi-Agent Orchestration vs. Single ReAct Agent

**Decision** A hierarchical six-agent system (Supervisor, System Mapper, three Tier Specialists, and a Cross-Tier Evaluator). Topology and rationale are detailed in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`agents.md`](agents.md).

**Alternative considered** A single ReAct agent that ingests the entire context bundle (Terraform plus four tiers of telemetry) upfront to produce a recommendation. By contrast, our design requires each specialist to pull only their relevant slice on demand via the MCP read surface.

**The "Why"** Bounding the scope enables deeper reasoning per specialist and produces a clean, legible audit trail rather than a tangled, single-agent thought process.

**Trade-off accepted** More LLM calls and higher latency per review. We accept this cost because this system is a review-tier recommender, not a high-throughput automation system. A single agent would be the right choice if sub-second latency outweighed reasoning depth, which does not apply here.

**How the eval-set validates this decision.** The "Rich" tier of the evaluator [`eval-set.md`](eval-set.md) is calibrated to expose this exact gap. A strong single-shot frontier model is expected to score 8-12 out of 18, whereas the orchestrated system targets 18/18. This expected gap defends the architectural complexity. If a single-shot model ever hits 18/18, the tier checks will tighten while the gold-standard answers remain constant.

## 2. ReAct Specialists vs. Zero-Shot Specialists

**Decision** Each Tier Specialist runs a ReAct loop against a constrained read surface to produce structured findings with explicit evidence-binding. See [`agents.md`](agents.md).

**Alternative considered** Zero-shot specialists. This would involve passing the entire context bundle (telemetry + sidecar) into a single LLM call per specialist to generate a recommendation. By contrast, our ReAct design pulls evidence incrementally, executing scoped reads on demand as the specialist's hypotheses evolve.

**The "Why"** A ReAct trace serves as a transparent investigation transcript, with every conclusion tied to a logged observation, whereas a zero-shot call is an unauditable leap from input to output.

**Trade-off accepted** Increased LLM calls and higher cost per specialist. This is acceptable because the resulting audit trail is central to the system's identity as a review tool. Zero-shot would be the correct choice for a high-throughput recommender where latency and cost outweigh audit depth, which does not apply here.

## 3. Recommender-Only vs Direct Remediation

**Decision** he system surfaces recommendations for human review but strictly avoids executing state changes. See principle 1 in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

**Alternative considered.** Automating low-risk resolutions (e.g., auto-applying cost-saving measures below a certain threshold).

**The "Why"** The logic required to generate a sound recommendation differs fundamentally from the safety constraints required to execute one. Mixing them creates competing architectural priorities.

**Trade-off accepted** A human remains in the loop to apply all changes. This prevents scope creep by bypassing complex external integrations (AWS APIs, Terraform, Jira) and keeps the focus strictly on the AI reasoning architecture. Because we do not execute remediations, the Action Harness is deliberately narrowed to enforcing read-only telemetry retrieval methods.

## 4. External Hugging Face Dataset vs. Monolithic Repository

**Decision** The 18 evaluation scenarios are published as a public Hugging Face dataset [`ameau01/synthesized-cloud-optimization-recommendations`](https://huggingface.co/datasets/ameau01/synthesized-cloud-optimization-recommendations). The custom three-tier evaluator (Floor, Mid, Rich) is maintained locally in `src/evaluator/` inside this project.

**Alternatives considered** Bundling the dataset directly in the repository, or bundling the evaluation logic into the Hugging Face dataset.

**The "Why"**

- **Single source of truth on Hugging Face.** Anyone who clones the project picks up the latest dataset via `huggingface_hub.snapshot_download`. A bundled copy silently drifts.
- **Real ML convention.** Public datasets get loaded via the `datasets` or library, not vendored. A reviewer who sees `snapshot_download` knows the project follows the convention.
- **Dataset stays neutral.** It ships data plus a tiny Floor sanity check. Scoring methodology is an opinion that belongs in a consumer project, not bundled with the data. Anyone evaluating against the dataset can pick their own scoring method.
- **Orchestration owns the discrimination story.** Floor / Mid / Rich tier semantics are how this project demonstrates that orchestration beats single-shot. Those tier checks are part of the project's contribution.
- **Two distinct artifacts read as engineering maturity.** The portfolio narrative becomes "I published the data, then I built a system that scores on it." Bundled looks like one monolithic homework project.

**Trade-off accepted** A 12MB initial download dependency. Bundling is appropriate for canonical benchmarks (like GLUE), but when the evaluation logic is a custom architectural contribution, strict separation is the better design.

## 5. Two-Tier LLM Mix (Haiku + Sonnet) vs. Single-Tier

**Decision** pecialists use Claude Haiku; the Cross-Tier Evaluator uses Claude Sonnet. See principle 6 in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

**Alternatives considered** Using exclusively Haiku (which struggles with complex cross-tier synthesis) or exclusively Sonnet (which wastes capability and budget on simple, high-volume ReAct loops).

**The "Why"** The cost-to-capability ratio across the system is non-uniform. Specialists execute many small, iterative turns where speed and cost dominate. The Evaluator executes a few large turns where reasoning capability dominates. Matching model strength exactly to the workload eliminates waste in both directions.

**Trade-off accepted.** Managing two model billing categories instead of one. The operational complexity is negligible (since both share the same provider and SDK), and the cost savings on the high-volume specialist tier are substantial.

### Cost estimation per review

While exact numbers depend on scenario complexity, the system is designed to be highly affordable to iterate on. A representative full review requires roughly 20–37 total LLM calls:

| Component                    | Calls                    | Notes                                                                     |
| ---------------------------- | ------------------------ | ------------------------------------------------------------------------- |
| Input Harness validation     | 0 LLM calls              | Pure schema validation.                                                   |
| Supervisor decisions         | 1, 2 LLM calls (Haiku)   | Light orchestration reasoning.                                            |
| System Mapper                | 1 LLM call (Haiku)       | Architecture model generation after Terraform parse.                      |
| Tier Specialist ReAct (per)  | 5, 10 LLM calls (Haiku)  | Depends on how many ReAct cycles the specialist needs.                    |
| Tier Specialists (all three) | 15, 30 LLM calls (Haiku) | Three specialists × 5, 10 cycles each.                                    |
| Cross-Tier Evaluator         | 3 LLM calls (Sonnet)     | Drift-check, cross-tier identification, synthesis.                        |
| Action Harness gate          | 0, 1 LLM call (Haiku)    | Structural checks are deterministic; severity classification may use LLM. |
| **Total per review**         | **20, 37 LLM calls**     | Mix of Haiku and Sonnet.                                                  |

### Cost-Aware Optimization Patterns

Beyond the model split, the architecture natively limits LLM spend through several design patterns:
- **Parallel Execution** Specialists run concurrently. This reduces wall-clock time without increasing call volume.
- **Supervisor Early-Skip** If the System Mapper's topology analysis indicates a specific tier is irrelevant to the current architecture, the Supervisor skips that specialist entirely.
- **Deterministic Guardrails** The Action Harness relies primarily on code-based checks rather than LLM calls to gate recommendations.
- **Append-Only Caching** Because the audit trail is append-only, the Evaluator's drift-check (a function mapping a finding to a verdict) can be cached during retries.

### Provider Portability

While the reference implementation uses Anthropic's Claude models, the architectural pattern is strictly provider-agnostic. The design simply dictates a fast/cheap model for structured data extraction and a heavy-reasoning model for synthesis. Substituting an equivalent two-tier split from OpenAI or Google is a basic configuration change, not an architectural rewrite.

## 6. Parallel vs. Sequential Specialists

**Decision** The three Tier Specialists run in parallel against independent tool surfaces, each strictly isolated to its own tier's data. See [`agents.md`](agents.md).

**Alternatives considered** Sequential execution (where one specialist's output feeds into the next) or a single multi-tier specialist reasoning across all three tiers simultaneously.

**The "Why"** Strict isolation ensures the Cross-Tier Evaluator's drift checks are meaningful. Because the specialists are structurally prevented from seeing each other's data, they cannot leak context or form correlated biases. Any cross-tier interactions the Evaluator identifies are therefore mathematically genuine.

**Trade-off accepted** Specialists cannot use cross-tier evidence to inform their own local analysis. We accept this because it deliberately centralizes cross-tier logic within the Evaluator, rather than diffusing that awareness across every specialist. As a secondary benefit, parallel execution reduces latency to the duration of the slowest specialist rather than the sum of all three.

## 7. Two-Level Confidence Model vs. Single Composite Score

**Decision** We use a two-tiered confidence model: Specialist-level (within-tier signals) and Evaluator-level (cross-tier consistency). See [`harnesses.md`](harnesses.md) section 2a.

**Alternative considered** A single composite confidence per recommendation.

**The "Why"** A specialist can accurately gauge its own local evidence strength but cannot assess systemic drift. Conversely, the Evaluator can measure cross-tier consistency but should not re-derive local signals. Separating the scores keeps each metric mathematically honest about exactly what it represents.

**Trade-off accepted.** The reviewer interface must display both scores, requiring users to interpret a slightly more complex breakdown. We accept this minor cognitive overhead for the human reviewer in exchange for a highly transparent, untangled confidence signal.

## 8. Hand-Crafted Synthetic Dataset vs. Real Telemetry

**Decision** The evaluation dataset consists of 18 hand-crafted scenarios, each meticulously reverse-engineered from a known target recommendation.

**Alternatives considered** Using real cloud telemetry from a live AWS account, public datasets, or purely LLM-generated random scenarios.

**The "Why"**

- **Ground truth** Synthetic data guarantees a known correct answer for benchmarking.
- **Guaranteed Edge Casese** It explicitly tests complex reasoning—like restraint, diagnostic deferral, and trade-offs—that live telemetry rarely guarantees on demand.
- **Strict Reproducibility** Any reviewer can run the exact same deterministic evaluation without requiring live AWS credentials.

**Trade-off accepted** The system is proven against synthetic scenarios, not live production noise. While this is an accepted limitation, building scenarios backwards from targeted edge cases acts as a deliberate stress test for the AI reasoning architecture, ensuring the evaluation is mathematically rigorous rather than environmentally dependent.

## System Limitations

Beyond the trade-offs tied to specific design decisions, the system operates within four hard boundaries:
- **Read-Only** It surfaces recommendations but never executes them. There is no automated actuation, rollback, or closed-loop learning from human decisions.
- **Stateless** It does not remember past reviews. Each execution is an isolated event; cross-review memory is deliberately kept out.
- **Idealized Data** It relies on synthetic telemetry. It has not been hardened against real-world noise like sensor drift, missing intervals, or partial outages.
- **Portfolio-Scoped** To keep the focus strictly on the core AI architecture, the scope is deliberately limited to a single application, three tiers, and a narrow recommendation whitelist.

## The Path to Production

In a live enterprise environment, these boundaries would be relaxed by introducing:
- Real telemetry connectors and a production observability stack.
- Bounded actuators behind the Action Harness for low-risk execution.
- Historical state tracking and cross-application aggregation.
- Closed-loop Human-in-the-Loop (HITL) model tuning.
- A dedicated reviewer UI and continuous monitoring triggers.

## What This Project Is Not

To maintain strict architectural focus, this system is explicitly:

- **Not a monitoring tool** It runs discrete, asynchronous reviews, not live streaming telemetry.
- **Not dynamically extensible** The tool surface is immutable. Agents cannot define new tools at runtime.
- **Not complexity for complexity's sake** Every agent layer is necessary and architecturally justified (see agents.md).
- **Not a knowledge graph** The structured audit trail is strictly relational, not semantic.


## The Point of This Document

A strong architecture is honest about its boundaries. Claims that exceed a project's reality are a red flag, while explicitly naming limits is a green flag. Every entry in this document follows the same shape: the alternative, the decision, the trade-off, and where the alternative would have been the right choice. The objective is not to argue that these designs are flawless, but to show they were made deliberately. The reasoning matters more than the conclusion.