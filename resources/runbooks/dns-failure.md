# DNS Failure

## Entry Condition

A workload has an observed Service or external-hostname lookup failure (for example NXDOMAIN or a DNS timeout), not merely a failed connection after successful resolution.

## Required Evidence

The failed hostname and lookup result. Pod DNS policy/nameservers, a known-good comparison, CoreDNS health/logs, and network-policy evidence are needed only when the initial result cannot isolate the cause.

## Tool Decisions

Reuse any lookup errors and workload configuration already available; `inspect_deployment_health` may not include a DNS lookup. Do not repeat Kubernetes reads or fetch Pod/CoreDNS logs merely because DNS failed. Obtain only the next DNS-specific evidence justified by the branch, using available capabilities.

## Workflow

Classify the observed lookup result, then take the first supported branch. Compare an affected and known-good Pod only if the scope remains unclear.

## Branches

1. **Hostname is incorrect or NXDOMAIN is isolated to that name:** correct the hostname or Service name.
2. **Only the affected Pod has incorrect DNS policy/nameservers:** correct that Pod configuration.
3. **Multiple workloads fail and CoreDNS is evidenced unhealthy:** investigate CoreDNS availability; its logs are optional evidence only if health data is insufficient.
4. **Lookup times out while DNS service is otherwise healthy:** investigate the affected network-policy or DNS traffic path.
5. **Scope or cause remains unknown:** use Escalation; do not assume CoreDNS is down.

## Stop Condition

Stop once the failed lookup mechanism and next action are clear; a known-good comparison is not mandatory when the hostname error is decisive.

## Escalation

If the lookup result cannot distinguish name, Pod configuration, DNS service, or network path, request only a targeted comparison or DNS-service evidence needed for that distinction.

## Recommendation

State the observed lookup error and the branch-specific correction. Do not invent DNS settings or network-policy rules.
