# Readiness Probe Failure

## Entry Condition

A running Pod is unready and its readiness probe is failing; Service endpoints may consequently exclude it. Do not attribute an unready Pod to a probe without supporting probe evidence.

## Required Evidence

The exact probe failure message and relevant path/port/command/timeout configuration. Response timing, dependency status, and Service endpoint membership are needed only to distinguish unresolved causes or impact.

## Tool Decisions

Start with container state and probe events already in `inspect_deployment_health`; do not repeat those reads. Do not fetch logs by default. Seek application/runtime evidence only if the probe result cannot identify the failure and existing routing indicates it is needed.

## Workflow

Match the probe message to the first supported branch before changing thresholds or application configuration.

## Branches

1. **Wrong path, port, or command is demonstrated:** correct that probe target.
2. **Timeout or connection failure during slow startup:** verify observed startup/response timing, then adjust probe timing only if it is the limiting factor.
3. **Probe reaches the app but a dependency fails:** address the evidenced dependency rather than relaxing readiness.
4. **No ready Service endpoints because selected Pods are unready:** resolve the probe failure first; if Pods are ready but endpoints are still absent, follow `k8s://runbooks/service-unreachable`.
5. **Probe message does not identify a cause:** use Escalation.

## Stop Condition

Stop when the probe failure mechanism and next corrective action are established; endpoint checks are not mandatory when the cause is already clear.

## Escalation

If the probe message and configuration are inconclusive, request only the relevant response/dependency evidence needed to distinguish the remaining branches.

## Recommendation

Recommend the demonstrated probe, startup-timing, or dependency correction. Do not invent timeout or threshold values.
