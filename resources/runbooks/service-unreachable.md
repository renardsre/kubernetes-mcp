# Service Unreachable

## Entry Condition

A Service name resolves, but a connection fails, times out, or is refused. If lookup itself fails, follow `k8s://runbooks/dns-failure` instead.

## Required Evidence

Service selector/port/targetPort, ready Endpoint or EndpointSlice membership, and selected Pod readiness as relevant. Application listening-port or network-policy evidence is needed only if endpoints and port mapping do not explain the failure.

## Tool Decisions

Reuse Pod readiness from `inspect_deployment_health` when present. That result may not contain Service or EndpointSlice data; obtain only the missing Service-specific evidence through available capabilities. Do not re-read Deployment/Pod evidence or fetch logs by default.

## Workflow

First determine whether the Service has ready endpoints matching the intended Pods; then take the first supported branch.

## Branches

1. **Selector matches no intended Pods:** correct the Service selector.
2. **Selected Pods exist but are unready, leaving no ready endpoints:** address the established readiness failure; use `k8s://runbooks/readiness-probe` only if a probe is the cause.
3. **Ready endpoints exist but port/targetPort maps incorrectly:** correct the demonstrated port mapping.
4. **Port mapping is correct but connections are refused:** verify the application's actual listening port and correct the evidenced mismatch.
5. **Connections time out with ready endpoints and valid port mapping:** investigate the relevant network policy or traffic path.
6. **Endpoint or failure evidence is unavailable:** use Escalation rather than guessing.

## Stop Condition

Stop when the selector, readiness, port, listener, or network-path mechanism is established and the next action is clear.

## Escalation

If ready-endpoint membership and port mapping do not distinguish the cause, request only targeted listener or traffic-path evidence needed for the unresolved branch.

## Recommendation

Name the failed connection stage and its branch-specific correction. Do not invent Service ports or network-policy changes.
