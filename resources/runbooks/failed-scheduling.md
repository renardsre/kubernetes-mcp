# FailedScheduling

## Entry Condition

`failure_class == "FailedScheduling"`: a Pod remains Pending and scheduler events report `FailedScheduling`.

## Required Evidence

The scheduler's rejected constraint and the affected Pod's resource requests, node selector/affinity, tolerations, or volume requirements as relevant. Node capacity/allocatable is needed only for a capacity-related event.

## Tool Decisions

Reuse `scheduling`, Pod configuration, and events from `inspect_deployment_health`. The container has not run; do not fetch application logs or repeat Pod/event reads to reconfirm scheduling failure.

## Workflow

Use the specific scheduler event to take the first applicable branch. If it reports multiple blockers, address the first concrete blocker and reassess scheduling afterward.

## Branches

1. **Volume or topology constraint:** resolve the stated volume placement/binding issue; if the claim itself is Pending, follow `k8s://runbooks/pvc-pending`.
2. **Node selector or affinity mismatch:** align the workload constraint with eligible node labels/affinity.
3. **Untolerated taint:** select an eligible node or add only the justified toleration.
4. **Insufficient CPU or memory:** compare requests with eligible nodes' allocatable capacity, then adjust requests or provide capacity based on evidence.
5. **No specific constraint is available:** use Escalation; do not assume capacity is the cause.

## Stop Condition

Stop when the scheduler event establishes the immediate blocker and the next action is clear; no logs are needed.

## Escalation

If the event is missing or conflicting, seek only the scheduler or eligible-node evidence required to identify the blocker. Reassess after a documented blocker is resolved.

## Recommendation

Name the rejected constraint and propose its corresponding correction. Do not invent node capacity, tolerations, or resource values.
