---
name: kubernetes-service-investigation
description: Investigate an exact Kubernetes Deployment or a logical application/service, resolving scope before inspecting relevant workloads and routing established failures to runbooks.
---

# Kubernetes Service Investigation

## Goal

Investigate the requested application scope with the existing aggregate MCP tools. Remain read-only unless the user explicitly requests a state-changing action.

## Scope Resolution

Distinguish an exact workload from a logical service before making calls:

- If the user explicitly names a Deployment (for example, `service-a-worker`), start with `inspect_deployment_health(namespace, name)` for that Deployment. Do not automatically inspect siblings.
- If the user means the whole service/application (for example, `service-a` or a Helm release), identify relevant workload candidates before inspecting them. In a known namespace, `find_unhealthy_deployments` can discover unhealthy Deployment candidates; inspect only candidates relevant to the request or evidence.

Prefer explicit workload names, then a shared Helm release/application instance or Kubernetes application labels (`app.kubernetes.io/instance`, `name`, `part-of`, `component`) **when those relationships are actually available in existing evidence**. Use a name relationship such as `service-a-*` only as a fallback heuristic, not proof of membership.

The current MCP tools do not enumerate Deployments by Helm release or application label, and discovery returns bounded unhealthy candidates without those relationships. Do not claim to have found every service component, infer healthy siblings, or fan out across unrelated workloads. State the scope limitation; ask for explicit workload names or stronger scope information if completeness matters. Do not inspect the same Deployment twice or expand scope after the requested question is answered.

## Evidence Routing

Use `failure_class` as the primary classification; use termination details, events, and container state as supporting evidence. Do not invent a class. Reuse the aggregate result instead of repeating Kubernetes reads.

If `evidence_sufficient=true` or `logs_recommended=false`, do not fetch logs merely to reconfirm the failure. Otherwise use `get_pod_logs` only for the first usable `recommended_log_targets` entry, with its pod, container, and `previous` value (100 lines by default). Respect `previous_logs_recommended` as a routing signal, but do not override an explicit target or invent one. No all-container or current-plus-previous fan-out; consider another target only if the first result is insufficient. If no usable target exists, report the evidence gap.

## Runbook Routing

For an established `failure_class`, use `search_runbooks` with that class and select the relevant **leaf** runbook. Otherwise search with the most specific observed symptom; use central `00-service-triage` only when the mechanism remains unknown or ambiguous. Never search by Deployment or namespace name, and never call `fetch_skill` with a failure class or runbook title. Failure-specific decisions belong to the runbook, not this Skill.

`search_runbooks` returns metadata, not the runbook body. Read the selected `k8s://runbooks/{slug}` Resource before claiming to follow its workflow. If this client cannot read MCP Resources, state that limitation and do not claim the runbook was read. Do not collect extra Kubernetes evidence solely because a runbook lists possible checks.

## Stop

For each relevant workload, stop when the failure mechanism and next action are clear, the runbook's stop condition is met, or further progress requires unavailable evidence/capability. Do not continue into sibling workloads unless the requested scope or evidence warrants it. Continue justified read-only investigation without asking permission; do not make changes without an explicit request.

## Final Response

Use these sections in order: `## Investigation Result`, `### Key Evidence`, `### Investigation`, `### Recommended Next Action`, `### Runbook`. Report the requested scope, workload(s) actually inspected, established failure class and root cause, concise evidence, and each meaningful action actually performed. Keep hypotheses under Recommended Next Action, not Root cause; never invent log evidence or tool calls.

End with exactly one truthful runbook status: `Runbook lookup: used — <title> (<URI>)` only if its body was read; `Runbook lookup: discovered, not read — <title> (<URI>)` if only metadata was obtained; `Runbook lookup: no useful match — <reason>`; or `Runbook lookup: skipped — <reason>`. If scope discovery was incomplete, state that explicitly.
