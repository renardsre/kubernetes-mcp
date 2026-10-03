import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fnmatch import fnmatchcase
from typing import cast

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

config.load_kube_config()

core = client.CoreV1Api()
apps = client.AppsV1Api()

RESOLVED_MATCH_LIMIT = 100


def api_error(exc: ApiException) -> RuntimeError:
    reason = exc.reason or "Kubernetes API error"
    if exc.status:
        return RuntimeError(
            f"Kubernetes API error {exc.status}: {reason}"
        )
    return RuntimeError(
        f"Kubernetes API error: {reason}"
    )


def event_timestamp(
    event: client.CoreV1Event,
) -> float:
    metadata = event.metadata
    creation_timestamp = (
        metadata.creation_timestamp
        if metadata is not None
        else None
    )
    timestamp = (
        event.last_timestamp
        or event.event_time
        or creation_timestamp
    )
    if not isinstance(timestamp, datetime):
        return 0.0
    return timestamp.timestamp()


def deployment_selector(
    deployment: client.V1Deployment,
) -> dict[str, str]:
    spec = deployment.spec
    if spec is None or spec.selector is None:
        return {}
    return cast(
        dict[str, str],
        spec.selector.match_labels or {},
    )


def labels_match(
    labels: dict[str, str] | None,
    selector: dict[str, str],
) -> bool:
    if not selector:
        return False

    labels = labels or {}
    return all(
        labels.get(key) == value
        for key, value in selector.items()
    )
def matching_pods(
    deployment: client.V1Deployment,
    pods: list[client.V1Pod],
) -> list[client.V1Pod]:
    """Return pods matching a Deployment selector."""
    selector = deployment_selector(deployment)
    if not selector:
        return []

    return [
        pod
        for pod in pods
        if labels_match(
            pod.metadata.labels if pod.metadata is not None else None,
            selector,
        )
    ]


def replica_set_revision(
    replica_set: client.V1ReplicaSet,
) -> int:
    metadata = replica_set.metadata
    annotations = (
        metadata.annotations
        if metadata is not None
        and metadata.annotations is not None
        else {}
    )
    raw = annotations.get(
        "deployment.kubernetes.io/revision",
        "0",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def owned_replica_sets(
    deployment_name: str,
    replica_sets: list[client.V1ReplicaSet],
) -> list[client.V1ReplicaSet]:
    owned: list[client.V1ReplicaSet] = []

    for replica_set in replica_sets:
        metadata = replica_set.metadata
        owners = (
            metadata.owner_references
            if metadata is not None
            and metadata.owner_references is not None
            else []
        )

        if any(
            owner.kind == "Deployment"
            and owner.name == deployment_name
            for owner in owners
        ):
            owned.append(replica_set)

    return owned


def current_replica_set(
    deployment_name: str,
    replica_sets: list[client.V1ReplicaSet],
) -> client.V1ReplicaSet | None:
    candidates = owned_replica_sets(
        deployment_name,
        replica_sets,
    )

    if not candidates:
        return None

    return max(
        candidates,
        key=replica_set_revision,
    )


def pods_owned_by_replica_set(
    replica_set_name: str,
    pods: list[client.V1Pod],
) -> list[client.V1Pod]:
    matched: list[client.V1Pod] = []

    for pod in pods:
        metadata = pod.metadata
        owners = (
            metadata.owner_references
            if metadata is not None
            and metadata.owner_references is not None
            else []
        )

        if any(
            owner.kind == "ReplicaSet"
            and owner.name == replica_set_name
            for owner in owners
        ):
            matched.append(pod)

    return matched


def container_state_summary(
    status: client.V1ContainerStatus,
    spec_container: client.V1Container | None = None,
) -> dict[str, object]:
    state_name = "unknown"
    reason = None
    message = None
    exit_code = None

    state = status.state
    if state is not None:
        if state.running is not None:
            state_name = "running"
        elif state.waiting is not None:
            state_name = "waiting"
            reason = state.waiting.reason
            message = state.waiting.message
        elif state.terminated is not None:
            state_name = "terminated"
            reason = state.terminated.reason
            message = state.terminated.message
            exit_code = state.terminated.exit_code

    last_termination: dict[str, object] | None = None
    last_reason = None

    last_state = status.last_state
    if (
        last_state is not None
        and last_state.terminated is not None
    ):
        terminated = last_state.terminated
        last_reason = terminated.reason
        last_termination = {
            "reason": terminated.reason,
            "exit_code": terminated.exit_code,
            "signal": terminated.signal,
            "message": terminated.message,
        }

    restart_count = status.restart_count or 0
    logs_available = (
        state_name in {"running", "terminated"}
        or restart_count > 0
        or last_termination is not None
    )

    if (
        reason == "CrashLoopBackOff"
        and last_reason
    ):
        primary_failure_reason = last_reason
    else:
        primary_failure_reason = (
            reason
            or last_reason
        )

    requests: dict[str, object] = {}
    limits: dict[str, object] = {}

    if (
        spec_container is not None
        and spec_container.resources is not None
    ):
        requests = dict(
            spec_container.resources.requests
            or {}
        )
        limits = dict(
            spec_container.resources.limits
            or {}
        )

    return {
        "name": status.name,
        "image": status.image,
        "ready": status.ready,
        "restart_count": restart_count,
        "state": state_name,
        "reason": reason,
        "message": message,
        "exit_code": exit_code,
        "last_termination": last_termination,
        "primary_failure_reason": (
            primary_failure_reason
        ),
        "resources": {
            "requests": requests,
            "limits": limits,
        },
        "logs_available": logs_available,
    }


def pod_health_summary(
    pod: client.V1Pod,
) -> dict[str, object]:
    metadata = pod.metadata
    spec = pod.spec
    status = pod.status

    container_statuses = (
        status.container_statuses
        if status is not None
        and status.container_statuses is not None
        else []
    )

    spec_containers = {
        item.name: item
        for item in (
            spec.containers
            if spec is not None
            and spec.containers is not None
            else []
        )
    }

    containers = [
        container_state_summary(
            item,
            spec_containers.get(item.name),
        )
        for item in container_statuses
    ]

    ready = bool(
        containers
        and all(
            bool(item["ready"])
            for item in containers
        )
    )

    primary_failure_reason = next(
        (
            item["primary_failure_reason"]
            for item in containers
            if item.get(
                "primary_failure_reason"
            )
        ),
        None,
    )

    node_selector = (
        dict(spec.node_selector or {})
        if spec is not None
        else {}
    )

    affinity_summary: dict[str, object] = {}
    if (
        spec is not None
        and spec.affinity is not None
    ):
        node_affinity = spec.affinity.node_affinity
        if node_affinity is not None:
            required = (
                node_affinity
                .required_during_scheduling_ignored_during_execution
            )
            preferred = (
                node_affinity
                .preferred_during_scheduling_ignored_during_execution
            )

            affinity_summary = {
                "required_node_affinity": (
                    required.to_dict()
                    if required is not None
                    else None
                ),
                "preferred_node_affinity": (
                    [
                        item.to_dict()
                        for item in preferred
                    ]
                    if preferred
                    else []
                ),
            }

    return {
        "name": (
            metadata.name
            if metadata is not None
            else None
        ),
        "phase": (
            status.phase
            if status is not None
            else None
        ),
        "ready": ready,
        "primary_failure_reason": (
            primary_failure_reason
        ),
        "node_selector": node_selector,
        "affinity": affinity_summary,
        "containers": containers,
    }


def deployment_health_summary(
    deployment: client.V1Deployment,
) -> dict[str, object]:
    metadata = deployment.metadata
    spec = deployment.spec
    status = deployment.status

    desired = (
        spec.replicas
        if spec is not None
        and spec.replicas is not None
        else 0
    )
    ready = (
        status.ready_replicas or 0
        if status is not None
        else 0
    )
    available = (
        status.available_replicas or 0
        if status is not None
        else 0
    )
    unavailable = (
        status.unavailable_replicas or 0
        if status is not None
        else 0
    )

    failing_conditions: list[dict[str, object]] = []
    if (
        status is not None
        and status.conditions is not None
    ):
        for condition in status.conditions:
            if (
                condition.status == "False"
                or condition.reason
                in {
                    "ProgressDeadlineExceeded",
                    "ReplicaFailure",
                }
            ):
                failing_conditions.append(
                    {
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message,
                    }
                )

    return {
        "name": (
            metadata.name
            if metadata is not None
            else None
        ),
        "desired": desired,
        "ready": ready,
        "available": available,
        "unavailable": unavailable,
        "healthy": (
            desired == ready
            and desired == available
            and unavailable == 0
        ),
        "conditions": failing_conditions,
    }


def compact_event(
    event: client.CoreV1Event,
) -> dict[str, object]:
    involved_object = event.involved_object
    return {
        "type": event.type,
        "reason": event.reason,
        "object": (
            f"{involved_object.kind}/{involved_object.name}"
            if involved_object is not None
            else None
        ),
        "message": event.message,
    }


def related_events(
    events: list[client.CoreV1Event],
    names: set[str],
    limit: int,
) -> list[dict[str, object]]:
    selected = [
        event
        for event in events
        if event.involved_object is not None
        and event.involved_object.name in names
    ]

    selected.sort(
        key=event_timestamp,
        reverse=True,
    )

    return [
        compact_event(event)
        for event in selected[:limit]
    ]


def post_start_failure_pods(
    pod_summaries: list[dict[str, object]],
    events: list[dict[str, object]],
) -> set[str]:
    """Find current crashing Pods with an explicit postStart failure event."""
    crashing_pods = {
        str(pod["name"]): sum(
            container.get("reason") == "CrashLoopBackOff"
            for container in cast(list[dict[str, object]], pod.get("containers", []))
        )
        for pod in pod_summaries
        if pod.get("name")
    }
    crashing_pods = {name: count for name, count in crashing_pods.items() if count}
    if not crashing_pods or any(count != 1 for count in crashing_pods.values()):
        return set()

    affected = {
        name
        for name in crashing_pods
        if any(
            event.get("object") == f"Pod/{name}"
            and (
                event.get("reason") == "FailedPostStartHook"
                or (
                    event.get("reason") == "Killing"
                    and event.get("message") == "FailedPostStartHook"
                )
            )
            for event in events
        )
    }
    return affected if affected == set(crashing_pods) else set()


def post_start_lifecycle_evidence(
    pods: list[client.V1Pod],
    affected_pods: set[str],
) -> list[dict[str, object]]:
    """Project only relevant hook configuration from Pods already fetched."""
    evidence: list[dict[str, object]] = []
    for pod in pods:
        name = pod.metadata.name if pod.metadata is not None else None
        if name not in affected_pods or pod.spec is None:
            continue
        for container in pod.spec.containers or []:
            lifecycle = getattr(container, "lifecycle", None)
            hook = getattr(lifecycle, "post_start", None)
            if hook is None:
                continue
            action = getattr(hook, "_exec", None)
            detail: dict[str, object] = {"configured": True}
            if action is not None:
                command = getattr(action, "command", None) or []
                detail = {
                    "exec": {
                        "command": [str(part)[:512] for part in command[:8]],
                    },
                }
                if len(command) > 8 or any(len(str(part)) > 512 for part in command):
                    detail["truncated"] = True
            evidence.append(
                {
                    "pod": name,
                    "container": container.name,
                    "post_start": detail,
                }
            )
    return evidence


def scheduling_failure_summary(
    pod_summaries: list[dict[str, object]],
    events: list[dict[str, object]],
) -> dict[str, object] | None:
    pending_pods = [
        pod
        for pod in pod_summaries
        if pod.get("phase") == "Pending"
    ]

    failed_events = [
        event
        for event in events
        if event.get("reason") == "FailedScheduling"
    ]

    if not pending_pods or not failed_events:
        return None

    latest = failed_events[0]

    return {
        "reason": "FailedScheduling",
        "message": latest.get("message"),
        "pending_pods": [
            {
                "pod": pod.get("name"),
                "node_selector": pod.get(
                    "node_selector"
                ),
                "affinity": pod.get("affinity"),
            }
            for pod in pending_pods
        ],
    }


def primary_workload_reason(
    pods: list[dict[str, object]],
    deployment: dict[str, object],
    events: list[dict[str, object]] | None = None,
) -> str | None:
    if events:
        has_failed_scheduling = any(
            event.get("reason") == "FailedScheduling"
            for event in events
        )
        has_pending_pod = any(
            pod.get("phase") == "Pending"
            for pod in pods
        )
        if has_failed_scheduling and has_pending_pod:
            return "FailedScheduling"

    for pod in pods:
        reason = pod.get("primary_failure_reason")
        if reason:
            return str(reason)

    conditions = cast(
        list[dict[str, object]],
        deployment.get("conditions", []),
    )
    for condition in conditions:
        reason = condition.get("reason")
        if reason:
            return str(reason)

    return None


def normalized_failure_class(
    pod_summaries: list[dict[str, object]],
    scheduling: dict[str, object] | None,
) -> str | None:
    """Classify the primary failure using Kubernetes state already collected."""
    if scheduling is not None:
        return "FailedScheduling"

    for pod in pod_summaries:
        reason = pod.get("primary_failure_reason")
        if not reason:
            continue

        containers = cast(
            list[dict[str, object]],
            pod.get("containers", []),
        )
        for container in containers:
            if not container.get("primary_failure_reason"):
                continue

            current_reason = container.get("reason")
            if isinstance(current_reason, str) and current_reason in {
                "ImagePullBackOff", "ErrImagePull"
            }:
                return current_reason

            if current_reason == "CrashLoopBackOff":
                last_termination = container.get("last_termination")
                if (
                    isinstance(last_termination, dict)
                    and last_termination.get("reason") == "OOMKilled"
                ):
                    return "OOMKilled"
                return "CrashLoopBackOff"
            break

        if isinstance(reason, str) and reason in {
            "ImagePullBackOff",
            "ErrImagePull",
            "OOMKilled",
            "CrashLoopBackOff",
        }:
            return reason
        return None

    return None


NO_LOG_REQUIRED_FAILURES = frozenset(
    {
        "OOMKilled",
        "ImagePullBackOff",
        "ErrImagePull",
        "InvalidImageName",
        "CreateContainerConfigError",
        "CreateContainerError",
    }
)


def evidence_guidance(
    failure_class: str | None,
    failure_signal: str | None = None,
) -> dict[str, object]:
    """Return deterministic hints about evidence sufficiency and log value."""
    if failure_class == "CrashLoopBackOff" and failure_signal == "FailedPostStartHook":
        return {
            "evidence_sufficient": True,
            "logs_recommended": False,
            "reason": "post_start_hook_event_identifies_the_immediate_failure_mechanism",
        }

    if failure_class == "FailedScheduling":
        return {
            "evidence_sufficient": True,
            "logs_recommended": False,
            "reason": "failed_scheduling_event_identifies_the_immediate_failure_mechanism",
        }

    if failure_class in NO_LOG_REQUIRED_FAILURES:
        return {
            "evidence_sufficient": True,
            "logs_recommended": False,
            "reason": (
                "kubernetes_state_already_identifies_"
                "the_immediate_failure_mechanism"
            ),
        }

    if failure_class == "CrashLoopBackOff":
        return {
            "evidence_sufficient": False,
            "logs_recommended": True,
            "reason": (
                "runtime_failure_requires_application_"
                "evidence"
            ),
        }

    return {
        "evidence_sufficient": False,
        "logs_recommended": False,
        "reason": "additional_evidence_may_be_needed",
    }


def inspect_deployment_health(
    namespace: str,
    name: str,
    event_limit: int = 8,
) -> dict[str, object]:
    """Return bounded health evidence for a known Deployment; use it first when the name is known. The result indicates when runtime logs may help."""
    if event_limit < 1 or event_limit > 20:
        raise ValueError(
            "event_limit must be between 1 and 20"
        )

    def read_deployment() -> client.V1Deployment:
        return cast(
            client.V1Deployment,
            apps.read_namespaced_deployment(
                name=name,
                namespace=namespace,
            ),
        )

    def read_pods() -> list[client.V1Pod]:
        result = cast(
            client.V1PodList,
            core.list_namespaced_pod(
                namespace=namespace,
            ),
        )
        return cast(
            list[client.V1Pod],
            result.items,
        )

    def read_events() -> list[client.CoreV1Event]:
        result = cast(
            client.CoreV1EventList,
            core.list_namespaced_event(
                namespace=namespace,
            ),
        )
        return cast(
            list[client.CoreV1Event],
            result.items,
        )

    def read_replica_sets() -> list[client.V1ReplicaSet]:
        result = cast(
            client.V1ReplicaSetList,
            apps.list_namespaced_replica_set(
                namespace=namespace,
            ),
        )
        return cast(
            list[client.V1ReplicaSet],
            result.items,
        )

    try:
        with ThreadPoolExecutor(
            max_workers=4,
        ) as executor:
            deployment_future = executor.submit(
                read_deployment
            )
            pods_future = executor.submit(
                read_pods
            )
            events_future = executor.submit(
                read_events
            )
            replica_sets_future = executor.submit(
                read_replica_sets
            )

            deployment = deployment_future.result()
            all_pods = pods_future.result()
            all_events = events_future.result()
            replica_sets = replica_sets_future.result()
    except ApiException as exc:
        raise api_error(exc) from exc

    current_rs = current_replica_set(
        name,
        replica_sets,
    )

    current_rs_name = (
        current_rs.metadata.name
        if current_rs is not None
        and current_rs.metadata is not None
        else None
    )

    if current_rs_name:
        workload_pods = pods_owned_by_replica_set(
            current_rs_name,
            all_pods,
        )
    else:
        selector = deployment_selector(
            deployment
        )
        workload_pods = [
            pod
            for pod in all_pods
            if labels_match(
                (
                    pod.metadata.labels
                    if pod.metadata is not None
                    else None
                ),
                selector,
            )
        ]

    deployment_summary = (
        deployment_health_summary(
            deployment
        )
    )
    pod_summaries = [
        pod_health_summary(pod)
        for pod in workload_pods
    ]

    related_names = {name}
    related_names.update(
        str(item["name"])
        for item in pod_summaries
        if item.get("name")
    )

    events = related_events(
        all_events,
        related_names,
        event_limit,
    )

    scheduling = scheduling_failure_summary(
        pod_summaries,
        events,
    )
    failure_class = normalized_failure_class(
        pod_summaries,
        scheduling,
    )
    affected_post_start_pods = (
        post_start_failure_pods(pod_summaries, events)
        if failure_class == "CrashLoopBackOff"
        else set()
    )
    failure_signal = (
        "FailedPostStartHook" if affected_post_start_pods else None
    )

    logs_available = any(
        bool(container.get("logs_available"))
        for pod in pod_summaries
        for container in cast(
            list[dict[str, object]],
            pod.get("containers", []),
        )
    )

    if scheduling is not None:
        logs_available = False

    guidance = evidence_guidance(failure_class, failure_signal)

    recommended_log_targets: list[dict[str, object]] = []
    if guidance["logs_recommended"]:
        for pod in sorted(
            pod_summaries, key=lambda item: str(item.get("name") or "")
        ):
            pod_name = pod.get("name")
            if not isinstance(pod_name, str):
                continue
            for container in cast(
                list[dict[str, object]], pod.get("containers", [])
            ):
                if not container.get("primary_failure_reason") or not container.get(
                    "logs_available"
                ):
                    continue
                if container.get("primary_failure_reason") in NO_LOG_REQUIRED_FAILURES:
                    continue
                container_name = container.get("name")
                if not isinstance(container_name, str):
                    continue
                recommended_log_targets.append(
                    {
                        "pod": pod_name,
                        "container": container_name,
                        "previous": bool(
                            container.get("last_termination") is not None
                            or container.get("restart_count")
                        ),
                    }
                )
                break
            if recommended_log_targets:
                break

    previous_logs_recommended = any(
        bool(target["previous"]) for target in recommended_log_targets
    )

    result: dict[str, object] = {
        "deployment": deployment_summary,
        "current_replica_set": current_rs_name,
        "pods": pod_summaries,
        "events": events,
        "scheduling": scheduling,
        "primary_failure_reason": primary_workload_reason(
            pod_summaries,
            deployment_summary,
            events,
        ),
        "failure_class": failure_class,
        "failure_signal": failure_signal,
        "logs_available": logs_available,
        "evidence_sufficient": guidance[
            "evidence_sufficient"
        ],
        "logs_recommended": guidance[
            "logs_recommended"
        ],
        "previous_logs_recommended": previous_logs_recommended,
        "recommended_log_targets": recommended_log_targets,
        "evidence_guidance_reason": guidance[
            "reason"
        ],
        "diagnosis_included": False,
    }
    if affected_post_start_pods:
        result["lifecycle"] = post_start_lifecycle_evidence(
            workload_pods,
            affected_post_start_pods,
        )
    return result


def resolve_workloads(
    namespace: str,
    kind: str,
    pattern: str,
    match_type: str,
) -> dict[str, object]:
    """Resolve names for one workload kind within one namespace."""
    if not namespace.strip() or not pattern.strip():
        raise ValueError("namespace and pattern must not be empty")
    if kind not in {"Deployment", "StatefulSet", "DaemonSet", "Pod"}:
        raise ValueError(f"Unsupported workload kind: {kind}")
    if match_type not in {
        "exact", "prefix", "glob", "substring", "token_match", "label_selector", "auto"
    }:
        raise ValueError(f"Unsupported match_type: {match_type}")

    options = {"label_selector": pattern} if match_type == "label_selector" else {}
    items: list[
        client.V1Deployment | client.V1StatefulSet | client.V1DaemonSet | client.V1Pod
    ] = []
    try:
        if kind == "Deployment":
            result = cast(
                client.V1DeploymentList,
                apps.list_namespaced_deployment(namespace=namespace, **options),
            )
            items.extend(result.items or [])
        elif kind == "StatefulSet":
            result = cast(
                client.V1StatefulSetList,
                apps.list_namespaced_stateful_set(namespace=namespace, **options),
            )
            items.extend(result.items or [])
        elif kind == "DaemonSet":
            result = cast(
                client.V1DaemonSetList,
                apps.list_namespaced_daemon_set(namespace=namespace, **options),
            )
            items.extend(result.items or [])
        else:
            result = cast(
                client.V1PodList,
                core.list_namespaced_pod(namespace=namespace, **options),
            )
            items.extend(result.items or [])
    except ApiException as exc:
        raise api_error(exc) from exc

    query_tokens = set(filter(None, re.split(r"[-._]+", pattern)))
    reasons = {
        "exact": "name equals pattern",
        "prefix": "name starts with pattern",
        "substring": "name contains pattern",
        "token_match": "all pattern tokens match name-token prefixes",
        "glob": "name matches glob pattern",
        "label_selector": "Kubernetes label selector matched",
    }
    priority = ("exact", "prefix", "substring", "token_match")
    matches: list[tuple[int, str, str]] = []
    for item in items:
        name = item.metadata.name if item.metadata is not None else None
        if not isinstance(name, str):
            continue
        if match_type == "label_selector":
            method = "label_selector"
        elif match_type == "glob":
            if not fnmatchcase(name, pattern):
                continue
            method = "glob"
        else:
            token_match = False
            if match_type in {"token_match", "auto"} and query_tokens:
                name_tokens = re.split(r"[-._]+", name)
                token_match = all(
                    any(name_token.startswith(token) for name_token in name_tokens)
                    for token in query_tokens
                )
            conditions = {
                "exact": name == pattern,
                "prefix": name.startswith(pattern),
                "substring": pattern in name,
                "token_match": token_match,
            }
            if match_type != "auto" and not conditions[match_type]:
                continue
            method = next((candidate for candidate in priority if conditions[candidate]), None)
            if method is None:
                continue
        matches.append((priority.index(method) if method in priority else len(priority), name, method))
    matches.sort(key=lambda match: (match[0], match[1]))
    return {
        "requested_pattern": pattern,
        "namespace": namespace,
        "kind": kind,
        "match_type": match_type,
        "match_count": len(matches),
        "matches": [
            {
                "name": name,
                "kind": kind,
                "namespace": namespace,
                "match_method": method,
                "match_reason": reasons[method],
            }
            for _, name, method in matches[:RESOLVED_MATCH_LIMIT]
        ],
        "resolved": len(matches) == 1,
        "truncated": len(matches) > RESOLVED_MATCH_LIMIT,
    }


def find_unhealthy_deployments(
    namespace: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Discover unhealthy Deployments in a namespace; use inspect_deployment_health for detailed evidence."""
    if limit < 1 or limit > 100:
        raise ValueError(
            "limit must be between 1 and 100"
        )

    def read_deployments() -> list[client.V1Deployment]:
        result = cast(
            client.V1DeploymentList,
            apps.list_namespaced_deployment(
                namespace=namespace,
            ),
        )
        return cast(
            list[client.V1Deployment],
            result.items,
        )

    def read_pods() -> list[client.V1Pod]:
        result = cast(
            client.V1PodList,
            core.list_namespaced_pod(
                namespace=namespace,
            ),
        )
        return cast(
            list[client.V1Pod],
            result.items,
        )

    try:
        with ThreadPoolExecutor(
            max_workers=2,
        ) as executor:
            deployments_future = executor.submit(
                read_deployments
            )
            pods_future = executor.submit(
                read_pods
            )

            deployments = (
                deployments_future.result()
            )
            all_pods = pods_future.result()
    except ApiException as exc:
        raise api_error(exc) from exc

    if not deployments and not all_pods:
        try:
            core.read_namespace(name=namespace)
        except ApiException as exc:
            raise api_error(exc) from exc

    unhealthy: list[dict[str, object]] = []

    for deployment in deployments:
        dep = deployment_health_summary(
            deployment
        )
        pods = [
            pod_health_summary(pod)
            for pod in matching_pods(
                deployment,
                all_pods,
            )
        ]

        reason = primary_workload_reason(
            pods,
            dep,
        )

        if bool(dep["healthy"]) and not reason:
            continue

        unhealthy.append(
            {
                "name": dep["name"],
                "desired": dep["desired"],
                "ready": dep["ready"],
                "available": dep["available"],
                "reason": reason,
                "pod_count": len(pods),
            }
        )

        if len(unhealthy) >= limit:
            break

    return unhealthy


def get_pod_logs(
    namespace: str,
    name: str,
    container: str = "",
    tail_lines: int = 100,
    previous: bool = False,
) -> dict[str, object]:
    """Return bounded pod runtime logs; previous=True reads a prior container execution."""
    if tail_lines < 1 or tail_lines > 500:
        raise ValueError(
            "tail_lines must be between 1 and 500"
        )

    kwargs: dict[str, object] = {
        "name": name,
        "namespace": namespace,
        "tail_lines": tail_lines,
        "timestamps": True,
        "previous": previous,
    }

    if container:
        kwargs["container"] = container

    try:
        logs = cast(
            str,
            core.read_namespaced_pod_log(
                **kwargs,
            ),
        )
    except ApiException as exc:
        raise api_error(exc) from exc

    return {
        "namespace": namespace,
        "pod": name,
        "container": container or None,
        "tail_lines": tail_lines,
        "previous": previous,
        "logs": logs,
    }
