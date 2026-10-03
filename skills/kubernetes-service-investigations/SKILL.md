---
name: kubernetes-service-investigation
description: Investigate a named Deployment, a Deployment name pattern (prefix or glob), or a logical application/service. Resolve workload patterns before inspection; namespace-wide health reviews use the namespace Skill.
---

# Kubernetes Service Investigation

## Goal

Investigate the requested application scope with the existing aggregate MCP tools. Remain read-only unless the user explicitly requests a state-changing action.

## Scope Resolution

Distinguish an exact workload, a workload pattern, and a logical service before making calls:

- If the user supplies a workload wildcard/glob or prefix (for example, `holmes-crash*`), call `resolve_workloads` with the original pattern, requested namespace and kind, and `glob` or `prefix` as appropriate before inspection. Inspect only relevant returned names.
- If the identifier looks exact, inspect that exact Deployment first. Only if it is **not found**, call `resolve_workloads` exactly once with the **original** identifier as `pattern` (no added `*`), requested namespace and kind, and `match_type="prefix"`. Treat this resolver result as authoritative: one candidate (`resolved=true`) → inspect that name; multiple → stop and ask for clarification; zero → report not found and stop. Do not treat other inspection errors as not found.
- If the user means the whole service/application (for example, `service-a` or a Helm release), identify relevant workload candidates before inspecting them. In a known namespace, `find_unhealthy_deployments` can discover unhealthy Deployment candidates; inspect only candidates relevant to the request or evidence.

For a supplied workload identifier, namespace-wide discovery is not target resolution. Before the target is resolved, do not call `find_unhealthy_deployments`, shorten or broaden the identifier, search runbooks, or inspect unrelated workloads. Do not substitute generic Kubernetes/core tools (`kubernetes_tabular_query`, `kubernetes_jq_query`, `kubernetes_count`) or shell commands (`bash`, `kubectl`, `grep`) for `resolve_workloads` when the exact name is not found.

Prefer explicit workload names, then a shared Helm release/application instance or Kubernetes application labels (`app.kubernetes.io/instance`, `name`, `part-of`, `component`) **when those relationships are actually available in existing evidence**. Use a name relationship such as `service-a-*` only as a fallback heuristic, not proof of membership.

`resolve_workloads` supports name patterns and label selectors within one namespace and kind, but does not prove complete logical-service membership. Namespace discovery returns bounded unhealthy candidates without those relationships. Do not claim to have found every service component, infer healthy siblings, or fan out across unrelated workloads. State the scope limitation if completeness matters. Do not inspect the same Deployment twice or expand scope after the requested question is answered.

## Runbook Routing

Lifecycle: resolve requested scope → collect minimal specialized evidence → identify a meaningful failure classification or actionable signal → **MUST search** for a relevant runbook → if found, **MUST read its Resource body** → follow its decision workflow → evaluate resulting evidence → repeat lookup only for a genuinely new, more-specific actionable signal → stop when diagnosis and next action are sufficient.

Once inspection of the resolved target establishes a meaningful `failure_class` or actionable `failure_signal`, **MUST use `search_runbooks` before continuing free-form evidence exploration**, even if the initial evidence is already sufficient. Search using the most specific established signal or class for a relevant leaf runbook. Target resolution alone does not trigger lookup. Use central `00-service-triage` only when the mechanism remains unknown or ambiguous. Never search by Deployment or namespace name, and never call `fetch_skill` with a failure class or runbook title.

If a relevant runbook exists, **MUST read/consume the selected MCP Resource body before additional evidence calls**, including logs, events, or descriptions. Search metadata does not mean the runbook was read or used. Runbook-directed evidence takes priority over generic exploration: follow its decision workflow, collect only evidence still required, and evaluate the result. Reuse evidence already available; do not collect extra Kubernetes evidence solely because a runbook lists possible checks.

If resulting evidence establishes a genuinely new, more-specific actionable signal, **MUST search for a more-specific runbook and read/follow it if available** before further exploration. Do not repeat lookup for the same signal/runbook without new evidence; reuse a Resource body already read during this investigation if the same runbook is selected again. If a successful search finds no relevant runbook, Skill/model reasoning from current evidence is allowed, with only justified evidence collection. A failed search or unavailable Resource read is not a no-match result: report the access gap and pause further evidence collection rather than bypassing the workflow. Once applicable routing is complete and diagnosis plus next action are sufficient, stop.

## Evidence Routing

Use `failure_class` as the primary classification; use `failure_signal`, termination details, events, and container state as supporting evidence. Do not invent a class or repeat evidence already returned by `inspect_deployment_health`. If inspection establishes a class or signal, finish Runbook Routing above before any further evidence calls.

After reading the runbook, or a confirmed no-match result, prefer curated Kubernetes MCP tools for a specific evidence gap. If `evidence_sufficient=true` or `logs_recommended=false`, do not fetch logs merely to reconfirm the failure. When the workflow requires logs and `logs_recommended=true`, use `get_pod_logs` only for the first usable `recommended_log_targets` entry, respecting its pod, container, and `previous` value; use the Tool schema for arguments and defaults. Do not fan out across containers or log modes. Use generic Kubernetes/core or bash/kubectl only for required evidence unavailable through curated MCP tools; never use them for broad duplicate inspection. If no usable evidence path exists, report the gap.

## Stop

For each relevant workload, complete mandatory Runbook Routing before stopping with an established diagnosis. Then stop when the failure mechanism and next action are clear, the runbook's stop condition is met, or further progress requires unavailable evidence/capability. Scope-resolution stops still apply before classification. Do not continue into sibling workloads unless the requested scope or evidence warrants it. Continue justified read-only investigation without asking permission; do not make changes without an explicit request.

## Final Response

Use these sections in order: `## Investigation Result`, `### Key Evidence`, `### Investigation`, `### Recommended Next Action`, `### Runbook`. Report the requested scope, workload(s) actually inspected, established failure class and root cause, concise evidence, and each meaningful action actually performed. Keep hypotheses under Recommended Next Action, not Root cause; never invent log evidence or tool calls.

End with exactly one truthful runbook status: `Runbook lookup: used — <title> (<URI>)` only if its body was read; `Runbook lookup: discovered, not read — <title> (<URI>)` if only metadata was obtained; `Runbook lookup: no useful match — <reason>`; or `Runbook lookup: skipped — <reason>`. If scope discovery was incomplete, state that explicitly.
