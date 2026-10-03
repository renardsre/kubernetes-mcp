---
name: kubernetes-namespace-investigation
description: Review unhealthy Kubernetes Deployments across a namespace when the user gives no workload name or pattern. Use namespace-bounded discovery, targeted inspection, and failure-specific runbooks.
---

# Kubernetes Namespace Investigation

## Goal

Review unhealthy workloads in the requested namespace only when no workload name or pattern was supplied. Remain read-only unless the user explicitly requests a state-changing action.

## Discover and Inspect

Start with `find_unhealthy_deployments(namespace)`. Its bounded results are unhealthy **Deployment** candidates, not a complete inventory of every workload type. If the result is empty, report that no unhealthy Deployments were returned; do not claim the whole namespace is healthy.

Inspect each relevant unhealthy Deployment once with `inspect_deployment_health`. Do not inspect healthy or unrelated Deployments without an explicit reason. Reuse returned rollout, Pod, container, scheduling, and event evidence instead of repeating reads.

## Per-Workload Routing

For each inspected candidate: minimal specialized evidence → meaningful failure classification/actionable signal → **MUST search** for a relevant leaf runbook → if found, **MUST read its MCP Resource body** → follow its decision workflow → evaluate evidence → stop when diagnosis and next action are sufficient. Discovery/target resolution alone does not trigger lookup.

Once a meaningful classification or actionable signal exists, **MUST use `search_runbooks` before continuing free-form evidence exploration**, even if current evidence is sufficient. Query the most specific established signal or class, not workload/namespace names; failure classes and runbook titles are not Skills. A matching runbook **MUST be read before additional evidence calls**. Search metadata alone is not consumption or use. Runbook-directed evidence takes priority over generic exploration; reuse inspection evidence and collect only what the workflow still requires. Central triage is for unresolved or ambiguous mechanisms.

If resulting evidence establishes a genuinely new, more-specific actionable signal, **MUST search for a more-specific runbook and read/follow it if available**. Do not repeat lookup for the same signal/runbook without new evidence; reuse a Resource body already read in this investigation when applicable. If a successful search finds no relevant runbook, Skill/model reasoning from current evidence is allowed. A failed search or unavailable Resource read is not a no-match result: report the access gap and pause that workload's evidence collection. If no mechanism can be established, report the evidence gap instead of guessing.

## Stop and Report

Complete mandatory per-workload routing before stopping with an established diagnosis. Then stop each workload's investigation once its failure mechanism and next action are clear, its runbook stop condition is met, or required evidence is unavailable. Summarize unhealthy Deployments, established failures, supporting evidence, next actions, and whether each runbook was read, only discovered, unmatched, or skipped. State when bounded discovery limits namespace-wide completeness. Do not make changes without an explicit request.
