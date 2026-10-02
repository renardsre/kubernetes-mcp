# OOMKilled

## Entry Condition

`failure_class == "OOMKilled"` or a container's termination reason is `OOMKilled` (often exit code `137`). Exit code alone is supporting evidence, not proof.

## Required Evidence

- Termination reason and exit code; affected container and restart count.
- That container's memory request and limit, plus CPU configuration for a resource recommendation.
- Recent memory usage and node memory pressure **if available**; neither is required to establish the immediate failure mechanism.

## Tool Decisions

Reuse container state, resources, and events already returned by `inspect_deployment_health`; do not repeat those Kubernetes reads. Termination evidence establishes the immediate `OOMKilled` mechanism. Do not run tool `get_pod_logs` or `fetch_pod_logs` merely to reconfirm it.

## Workflow

1. Confirm which container was `OOMKilled` and its configured memory request/limit.
2. If metrics exist, compare peak usage with the limit: sustained near-limit use, short spikes, or continuous growth suggest different next actions. Without metrics, do not invent a production size.
3. Take the first applicable branch below; recommend a change only for the affected container.

## Branches

1. **Node memory pressure is evidenced:** investigate node capacity/pressure before resizing the container; do not assume the container limit alone explains it.
2. **Memory usage grows continuously or without bound:** investigate a possible leak or workload growth before assuming simple undersizing.
3. **Observed usage consistently approaches the limit, or the configured limit is clearly insufficient:** size with measured peak usage and headroom when available. For the affected container with an existing `16Mi` request / `32Mi` limit, consider the starting trial under Recommendation, subject to quota and node capacity.
4. **Memory metrics are unavailable and no earlier branch applies:** do not require an extra tool call solely for metrics. Use the starting trial only if the affected container's existing configuration makes it appropriate; otherwise state that exact production sizing is unknown and must be validated against subsequent usage.

## Stop Condition

Stop evidence collection once the `OOMKilled` termination is established and the next action is clear. Missing memory metrics do not require application logs to establish this failure mechanism.

## Escalation

If failures recur or sizing/memory behavior remains unclear, request memory telemetry and capacity review before choosing a production limit. Do not automatically recommend HPA or VPA; consider scaling only when workload demand or traffic evidence supports it.

## Recommendation

For the current test case, `16Mi` request / `32Mi` limit is the affected container's **existing configuration**, not the recommendation. When this baseline applies, give this explicit **starting trial per affected container**, not universal production sizing:

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "256Mi"
    cpu: "500m"
```

Before applying it, verify namespace quota and node capacity. Afterward, confirm peak memory stays below `256Mi` with headroom, no new `OOMKilled` events occur, and restart count and memory growth stabilize. Include these concrete values when this baseline applies; do not replace them with only “increase memory limits.”

CPU does not cause `OOMKilled`: `100m`/`500m` are example starting values, not a reason to raise CPU without separate evidence of pressure or throttling. If throttling is independently confirmed, adjust the CPU limit based on observed usage and policy.
