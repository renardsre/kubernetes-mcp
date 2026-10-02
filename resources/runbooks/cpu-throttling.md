# CPU Throttling

## Entry Condition

Suspect CPU throttling when latency rises near a container's CPU limit; confirm correlation with observed throttling before attributing the latency to it.

## Required Evidence

CPU requests/limits and a throttling-versus-latency observation. Workload concurrency, burst behavior, and node CPU pressure are relevant only when needed to distinguish the cause.

## Tool Decisions

Reuse resource configuration already returned by `inspect_deployment_health`. Throttling and latency metrics, when available from existing monitoring, are more useful here than Pod logs; do not fetch logs or repeat Kubernetes reads by default. If metrics are unavailable, do not claim throttling is proven.

## Workflow

Compare the timing of throttling and latency, then take the first supported branch before changing requests or limits.

## Branches

1. **Node CPU pressure is evidenced:** investigate node contention/capacity before changing this container's limit.
2. **Throttling coincides with latency and the container limit constrains bursts:** size or adjust the CPU limit based on observed usage and policy.
3. **High concurrency drives demand without a demonstrated limit bottleneck:** investigate concurrency or application demand before changing CPU limits.
4. **Latency occurs without correlated throttling:** investigate another latency cause; do not attribute it to CPU throttling.
5. **Throttling/latency evidence is unavailable or inconclusive:** use Escalation; do not invent a CPU diagnosis.

## Stop Condition

Stop when the limiting mechanism and next action are supported by correlated evidence. No exact CPU request or limit is implied by this runbook.

## Escalation

If correlation or source of contention remains unclear, request only the missing throttling, latency, concurrency, or node-pressure evidence needed to choose a branch.

## Recommendation

Report the observed correlation and one branch-specific action. Do not invent CPU configuration values or recommend raising limits based on latency alone.
