# Node NotReady

## Entry Condition

A Node condition reports `NotReady`; affected workloads may be unschedulable, evicted, or unavailable. Workload symptoms alone do not establish a node failure.

## Required Evidence

The Node condition and recent event identifying the immediate problem. Kubelet status, node reachability, disk/memory/PID pressure, credentials, and infrastructure health are needed only when the condition/event points to them or is inconclusive.

## Tool Decisions

Reuse relevant scheduling/workload evidence from `inspect_deployment_health` if already present, but do not treat it as a substitute for Node condition evidence. Seek only the missing node-specific evidence through available capabilities; application Pod logs are not the default diagnostic source for `NotReady`.

## Workflow

Interpret the Node condition and latest relevant event first; take the first supported branch to distinguish node-local pressure from control-plane communication failure.

## Branches

1. **Disk, memory, or PID pressure is reported:** address the evidenced local resource pressure.
2. **Kubelet is unhealthy or stopped:** investigate and restore kubelet operation.
3. **Node cannot reach the control plane or network path is broken:** investigate the demonstrated connectivity failure.
4. **Credential or certificate failure is reported:** renew or correct the affected node credential through the approved procedure.
5. **Node infrastructure failure or no decisive condition/event:** use Escalation; do not guess a local pressure cause.

## Stop Condition

Stop when the Node condition/event establishes the immediate failure mechanism and one operational action is clear.

## Escalation

If Node conditions and events do not distinguish kubelet, network, pressure, credential, or infrastructure failure, request only the corresponding node-specific evidence or involve the node operator.

## Recommendation

Name the affected Node, the observed condition, and its branch-specific next action. Do not invent resource thresholds or remediation commands.
