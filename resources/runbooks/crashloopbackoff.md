# CrashLoopBackOff

## Entry Condition

`failure_class == "CrashLoopBackOff"`. Repeated starts and exits are a symptom, not the root cause; handle any more specific `failure_signal` or termination/event mechanism before generic CrashLoop investigation.

## Required Evidence

- Container state, waiting message, last termination reason/message and exit code, restart count, relevant Pod events, resource configuration, and existing `failure_class`/`failure_signal` from `inspect_deployment_health`.
- For a lifecycle-hook event, the affected container's `lifecycle.post_start` or `lifecycle.pre_stop` configuration if available in the inspection result.
- Targeted container output only when that structured evidence does not explain the runtime failure.

Evidence already present in the inspection result is not a reason for additional Pod or Deployment reads.

## Tool Decisions

Inspect the existing evidence first. A specific termination reason or Pod event takes precedence over generic CrashLoop logs. Only when the mechanism remains unknown and `logs_recommended=true`, call `get_pod_logs` for **only the first `recommended_log_targets` entry**, using its pod, container, and `previous` value (default 100 lines). Do not guess a target, fan out across containers, or fetch both current and previous logs speculatively. If no usable target is supplied, escalate instead of guessing.

## Workflow

1. Check termination state and Pod events for a specific mechanism; use the matching branch first.
2. Only if that mechanism remains unknown, read the single recommended log target when logs are recommended.
3. If targeted logs are non-diagnostic, seek only Kubernetes evidence specific to the remaining mechanism; stop when the mechanism and next action are clear.

## Branches

- **`OOMKilled` is established by Kubernetes termination evidence:** continue at `k8s://runbooks/oomkilled`; do not fetch logs merely to reconfirm it.
- **`FailedPostStartHook` is established by a current Pod event or `failure_signal`:** use the affected container's `lifecycle.post_start` configuration and waiting/last-termination status already returned by inspection. Identify the hook action; do not collect broad application logs merely to rediscover the hook failure. If the next corrective check is clear, stop. Otherwise request evidence specific to that hook's execution. Do not execute the hook command: a command such as `php artisan migrate --force` may change application or database state.
- **A `FailedPreStopHook` or probe, image, scheduling, mount, eviction, or node-pressure event appears:** determine whether it actually explains this restart, then address that specific mechanism or follow its runbook; do not assume every historical event caused the current CrashLoop.
- **Another specific failure is established by structured evidence:** follow its matching runbook, if available, rather than continuing generic CrashLoop investigation.
- **Cause unknown, but `logs_recommended=false` or `recommended_log_targets` is empty/unusable:** do not invent a target, fetch arbitrary container logs, or try both current and previous; escalate using the structured Kubernetes evidence already available.
- **Targeted logs identify a specific failure class:** follow that class's runbook, if available.
- **Targeted logs identify an application startup, configuration, dependency, or command failure:** recommend correcting the specific observed failure, not the generic `CrashLoopBackOff` symptom.
- **Targeted logs remain inconclusive:** inspect only mechanism-specific Kubernetes evidence not already returned, then use Escalation if still unresolved; do not automatically query every container or both log modes.

## Stop Condition

Stop when the failure mechanism is established and one justified next action is clear, whether from structured evidence or the targeted logs.

## Escalation

If structured Kubernetes evidence alone, or that evidence plus a single targeted log result, cannot identify the cause, report what remains unknown and request only the next evidence justified by that gap. Do not present a suspected cause as confirmed.

## Recommendation

Recommend the branch-specific corrective action supported by the termination state, events, or targeted logs. Do not recommend a generic restart or resource increase without evidence.
