# Kubernetes Service Triage

## Purpose

Use this runbook only when the failure mechanism remains unknown or ambiguous
after reviewing available Kubernetes evidence. If a specific mechanism is
already established, use its leaf runbook directly instead.

## Evidence to Interpret

Reuse the Deployment, Pod, container, termination, scheduling, and event
evidence already available from `inspect_deployment_health`. Its
`failure_class` is a normalized operational class; `failure_signal` may
identify a more specific mechanism. A generic `primary_failure_reason` does
not override either field.

An exit code of `137` alone does not establish `OOMKilled`, and a Pending Pod
alone does not establish `FailedScheduling`. Look for the corresponding
termination reason or scheduler event before choosing those leaf runbooks.

## Workflow

1. Separate the observed symptom from a supported failure mechanism using the
   most specific current termination state, event, or configuration evidence.
2. If that evidence establishes a mechanism, select the corresponding leaf
   runbook; this central runbook is no longer needed.
3. If multiple mechanisms remain plausible, identify the single missing fact
   that would distinguish them. Do not treat missing evidence as proof of one
   branch.

## Stop Condition

Stop when the mechanism and next operational action are clear, or when the
remaining uncertainty cannot be resolved from available evidence.

## Escalation

If the available evidence cannot distinguish the remaining mechanisms, report
the uncertainty and the specific evidence needed next. Do not guess a leaf
runbook or broaden investigation without a reason.
