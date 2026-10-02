---
name: kubernetes-namespace-investigation
description: Review unhealthy Kubernetes Deployments in one namespace using bounded discovery, targeted inspection, and failure-specific runbooks.
---

# Kubernetes Namespace Investigation

## Goal

Review unhealthy workloads in the requested namespace. Remain read-only unless the user explicitly requests a state-changing action.

## Discover and Inspect

Start with `find_unhealthy_deployments(namespace)`. Its bounded results are unhealthy **Deployment** candidates, not a complete inventory of every workload type. If the result is empty, report that no unhealthy Deployments were returned; do not claim the whole namespace is healthy.

Inspect each relevant unhealthy Deployment once with `inspect_deployment_health`. Do not inspect healthy or unrelated Deployments without an explicit reason. Reuse returned rollout, Pod, container, scheduling, and event evidence instead of repeating reads.

## Per-Workload Routing

Use each inspection's classification and evidence guidance without independently reclassifying the workload or repeating sufficient evidence. Consult a relevant leaf runbook when its operational guidance is useful; central triage is for unresolved or ambiguous mechanisms. Distinguish a runbook discovered through metadata from one whose Resource body was actually read. If the available evidence cannot establish a mechanism, report the gap instead of guessing.

## Stop and Report

Stop each workload's investigation once its failure mechanism and next action are clear, its runbook stop condition is met, or required evidence is unavailable. Summarize unhealthy Deployments, established failures, supporting evidence, next actions, and whether each runbook was read, only discovered, unmatched, or skipped. State when bounded discovery limits namespace-wide completeness. Do not make changes without an explicit request.
