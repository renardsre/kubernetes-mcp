# PVC Pending

## Entry Condition

A PersistentVolumeClaim is Pending and a dependent Pod cannot start, or the Pod's scheduling evidence identifies an unbound claim. Do not infer PVC failure from a Pending Pod alone.

## Required Evidence

The claim's binding/provisioning event, requested storage, and StorageClass. Provisioner status, matching PersistentVolumes, access mode, and topology matter only when the event points to them or the immediate blocker remains unclear.

## Tool Decisions

Reuse any volume or scheduling evidence already in `inspect_deployment_health`. That result may not include PVC events; seek the specific claim event only if needed to distinguish binding from provisioning. A container that has not started has no useful application logs for this failure.

## Workflow

Use the most specific PVC event or known binding state, then take the first supported branch; do not enumerate unrelated volumes.

## Branches

1. **StorageClass is missing or invalid:** select or correct the intended StorageClass.
2. **Dynamic provisioning fails or the provisioner is unavailable:** investigate the named provisioner and its reported error.
3. **No matching volume or insufficient storage capacity:** provide compatible capacity or adjust the request based on evidence.
4. **Access mode or topology is incompatible:** align the claim and available volume/zone constraints.
5. **Binding/provisioning reason is unknown:** use Escalation; do not assume a capacity shortage.

## Stop Condition

Stop when the claim's immediate binding/provisioning blocker and next action are clear; Pod logs are not needed to establish it.

## Escalation

If claim events do not identify the blocker, request only the relevant provisioner, volume, or topology evidence needed to resolve that ambiguity.

## Recommendation

State the claim's observed blocker and one corresponding correction. Do not invent storage size, access mode, or StorageClass values.
