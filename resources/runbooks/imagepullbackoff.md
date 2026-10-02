# ImagePullBackOff

## Entry Condition

`failure_class` is `ImagePullBackOff` or `ErrImagePull`, supported by container state or image-pull events. The container has not started.

## Required Evidence

Affected image name/tag and the specific pull event or waiting message. `imagePullSecrets`, registry authentication, node reachability, and image architecture matter only when the error points to them.

## Tool Decisions

Use container state, image reference, and events already in `inspect_deployment_health`; do not repeat those reads. Application logs cannot explain a pull failure before startup, so do not call `get_pod_logs` to reconfirm it.

## Workflow

Read the most specific pull error, then take the first supported branch below. Do not infer a registry outage from a generic back-off message.

## Branches

1. **Image/tag not found, invalid reference, or unsupported architecture:** correct the image reference or select an architecture-compatible image.
2. **Authentication/authorization denied:** verify the intended `imagePullSecrets` and registry access for this workload.
3. **Registry DNS, connection, or timeout error:** investigate registry reachability from the affected node or cluster path.
4. **Only a generic back-off is visible:** use Escalation; do not guess which of the above caused it.

## Stop Condition

Stop when the pull event identifies the failure mechanism and one corrective action is clear; no application logs are needed.

## Escalation

If the pull event is absent or ambiguous, request only the missing image-pull or registry evidence needed to distinguish the branches. Do not broadly inspect unrelated Pods.

## Recommendation

Report the affected image and exact pull error, then recommend the branch-specific correction. Do not invent credentials, tags, or registry settings.
