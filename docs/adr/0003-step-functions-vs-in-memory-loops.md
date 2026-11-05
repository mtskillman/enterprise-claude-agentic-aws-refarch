# ADR 0003: Step Functions Distributed State Machines vs. In-Memory Agent Loops

## Status
Accepted

## Context
Agentic systems execute multi-step reasoning cycles: prompt generation, LLM inference, tool invocation, result parsing, reflection, and iterative re-prompting until goal satisfaction or maximum iterations are met. Traditional frameworks (e.g., in-process LangChain/LangGraph or AutoGen) run these loops inside a long-running container or Lambda process.

## Decision
We decouple the agent control loop into an **AWS Step Functions Distributed State Machine**, delegating individual tool invocations and model calls to isolated, stateless AWS Lambda functions.

## Consequences

### Positive
- **Fault-Tolerance & Long-Running Durability:** If a tool call or external API experiences transient outages or latency spikes, Step Functions provides native retry policies with exponential backoff and jitter without consuming compute memory. Execution state persists up to 1 year.
- **Auditable Execution Traceability:** Every reasoning step, tool payload, and model response is visually mapped and auditable in the Step Functions console, eliminating black-box debugging.
- **Cost Efficiency:** Eliminates idle compute charges while waiting on external APIs or asynchronous human-in-the-loop approvals (`Wait for Task Token`).
- **Blast-Radius Isolation:** Failures in individual tool modules cannot crash the orchestrator process.

### Trade-offs
- Adds small orchestrator transition latency (~15–30ms per state) compared to purely local in-memory thread execution.
- Requires defining state transitions in Amazon States Language (ASL) or Terraform.
