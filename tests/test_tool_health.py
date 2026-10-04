import asyncio
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from kubernetes.client import V1Container
from kubernetes.client.exceptions import ApiException
from mcp import Client

from mcp_server import create_mcp_server
from services import kubernetes as service

MCP = create_mcp_server()


def container_status(
    reason: str,
    last_reason: str | None = None,
    exit_code: int | None = None,
    name: str = "app",
) -> SimpleNamespace:
    last_state = (
        SimpleNamespace(
            terminated=SimpleNamespace(
                reason=last_reason,
                exit_code=exit_code,
                signal=None,
                message=None,
            )
        )
        if last_reason is not None
        else None
    )
    return SimpleNamespace(
        name=name,
        image="app:1",
        ready=False,
        restart_count=1 if last_reason else 0,
        state=SimpleNamespace(
            running=None,
            waiting=SimpleNamespace(reason=reason, message=None),
            terminated=None,
        ),
        last_state=last_state,
    )


class ToolHealthTests(unittest.TestCase):
    def test_find_unhealthy_deployments_valid_empty_namespace(self) -> None:
        apps = Mock()
        apps.list_namespaced_deployment.return_value = SimpleNamespace(items=[])
        core = Mock()
        core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

        with patch.object(service, "apps", apps), patch.object(service, "core", core):
            self.assertEqual(service.find_unhealthy_deployments("sandbox"), [])

        core.read_namespace.assert_called_once_with(name="sandbox")

    def test_find_unhealthy_deployments_missing_namespace(self) -> None:
        apps = Mock()
        apps.list_namespaced_deployment.return_value = SimpleNamespace(items=[])
        core = Mock()
        core.list_namespaced_pod.return_value = SimpleNamespace(items=[])
        core.read_namespace.side_effect = ApiException(status=404, reason="Not Found")

        with (
            patch.object(service, "apps", apps),
            patch.object(service, "core", core),
            self.assertRaisesRegex(RuntimeError, "Kubernetes API error 404"),
        ):
            service.find_unhealthy_deployments("does-not-exist")

    def inspect(
        self,
        reason: str,
        last_reason: str | None = None,
        exit_code: int | None = None,
        phase: str = "Running",
        scheduling: bool = False,
        other_statuses: list[SimpleNamespace] | None = None,
        primary_status: SimpleNamespace | None = None,
        hook_event_pod: str | None = None,
        post_start_command: list[str] | None = None,
        spec_containers: list[V1Container] | None = None,
        status_available: bool = True,
    ) -> dict[str, object]:
        first_status = primary_status or container_status(reason, last_reason, exit_code)
        deployment = SimpleNamespace(
            metadata=SimpleNamespace(name="demo"),
            spec=SimpleNamespace(replicas=1, selector=SimpleNamespace(match_labels={"app": "demo"})),
            status=SimpleNamespace(
                ready_replicas=0,
                available_replicas=0,
                unavailable_replicas=1,
                conditions=[],
            ),
        )
        replica_set = SimpleNamespace(
            metadata=SimpleNamespace(
                name="demo-rs",
                annotations={"deployment.kubernetes.io/revision": "1"},
                owner_references=[SimpleNamespace(kind="Deployment", name="demo")],
            )
        )
        pod = SimpleNamespace(
            metadata=SimpleNamespace(
                name="demo-pod",
                owner_references=[SimpleNamespace(kind="ReplicaSet", name="demo-rs")],
            ),
            spec=SimpleNamespace(
                containers=spec_containers if spec_containers is not None else [
                    SimpleNamespace(
                        name=status.name,
                        image=status.image,
                        command=None,
                        args=None,
                        resources=None,
                        lifecycle=(
                            SimpleNamespace(
                                post_start=SimpleNamespace(
                                    _exec=SimpleNamespace(command=post_start_command)
                                )
                            )
                            if status.name == first_status.name and post_start_command
                            else None
                        ),
                    )
                    for status in [
                        first_status,
                        *(other_statuses or []),
                    ]
                ],
                node_selector=None,
                affinity=None,
            ),
            status=SimpleNamespace(
                container_statuses=[
                    first_status,
                    *(other_statuses or []),
                ],
                phase=phase,
            ) if status_available else None,
        )
        events = [
            SimpleNamespace(
                involved_object=SimpleNamespace(kind="Pod", name="demo-pod"),
                type="Warning",
                reason="FailedScheduling",
                message="0/1 nodes are available",
                last_timestamp=None,
                event_time=None,
                metadata=SimpleNamespace(creation_timestamp=None),
            )
        ] if scheduling else []
        if hook_event_pod is not None:
            events.extend(
                [
                    SimpleNamespace(
                        involved_object=SimpleNamespace(kind="Pod", name=hook_event_pod),
                        type="Warning",
                        reason="FailedPostStartHook",
                        message="PostStartHook failed",
                        last_timestamp=None,
                        event_time=None,
                        metadata=SimpleNamespace(creation_timestamp=None),
                    ),
                    SimpleNamespace(
                        involved_object=SimpleNamespace(kind="Pod", name=hook_event_pod),
                        type="Normal",
                        reason="Killing",
                        message="FailedPostStartHook",
                        last_timestamp=None,
                        event_time=None,
                        metadata=SimpleNamespace(creation_timestamp=None),
                    ),
                ]
            )

        mock_apps = Mock()
        mock_apps.read_namespaced_deployment.return_value = deployment
        mock_apps.list_namespaced_replica_set.return_value = SimpleNamespace(
            items=[replica_set]
        )
        mock_core = Mock()
        mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])
        mock_core.list_namespaced_event.return_value = SimpleNamespace(items=events)

        with patch.object(service, "apps", mock_apps), patch.object(service, "core", mock_core):
            result = service.inspect_deployment_health("sandbox", "demo")

        mock_apps.read_namespaced_deployment.assert_called_once_with(
            name="demo", namespace="sandbox"
        )
        mock_apps.list_namespaced_replica_set.assert_called_once_with(
            namespace="sandbox"
        )
        mock_core.list_namespaced_pod.assert_called_once_with(namespace="sandbox")
        mock_core.list_namespaced_event.assert_called_once_with(namespace="sandbox")
        mock_core.read_namespaced_pod_log.assert_not_called()
        self.assertEqual(len(mock_apps.mock_calls) + len(mock_core.mock_calls), 4)
        return result

    def test_execution_configuration_is_exposed_without_status(self) -> None:
        command = ["/bin/sh", "-c"]
        args = ['echo "database connection failed"; exit 1']
        for status_available in (True, False):
            with self.subTest(status_available=status_available):
                result = self.inspect(
                    "CrashLoopBackOff", "Error", 1,
                    spec_containers=[V1Container(
                        name="app", image="example/app:test", command=command, args=args,
                    )],
                    status_available=status_available,
                )
                pod = cast(list[dict[str, object]], result["pods"])[0]
                self.assertEqual(pod["container_execution"], [{
                    "name": "app",
                    "source": "pod.spec.containers",
                    "image": "example/app:test",
                    "command": command,
                    "args": args,
                    "truncated_fields": [],
                }])

    def test_execution_defaults_do_not_invent_image_entrypoint(self) -> None:
        for value in (None, []):
            with self.subTest(value=value):
                result = self.inspect("ContainerCreating", spec_containers=[
                    V1Container(name="app", image="example/app:test", command=value, args=value),
                ])
                pod = cast(list[dict[str, object]], result["pods"])[0]
                config = cast(list[dict[str, object]], pod["container_execution"])[0]
                self.assertEqual(config["command"], value)
                self.assertEqual(config["args"], value)
                self.assertEqual(config["truncated_fields"], [])

    def test_execution_configuration_preserves_container_identity(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "Error", 1,
            other_statuses=[container_status("Running", name="sidecar")],
            spec_containers=[
                V1Container(name="sidecar", image="sidecar:2", command=["/proxy"], args=["--serve"]),
                V1Container(name="app", image="app:2", command=["/app"], args=["--start"]),
            ],
        )
        pod = cast(list[dict[str, object]], result["pods"])[0]
        configs = {
            item["name"]: item
            for item in cast(list[dict[str, object]], pod["container_execution"])
        }
        self.assertEqual(
            (configs["app"]["image"], configs["app"]["command"], configs["app"]["args"]),
            ("app:2", ["/app"], ["--start"]),
        )
        self.assertEqual(
            (configs["sidecar"]["image"], configs["sidecar"]["command"], configs["sidecar"]["args"]),
            ("sidecar:2", ["/proxy"], ["--serve"]),
        )

    def test_execution_configuration_is_bounded_and_marks_truncation(self) -> None:
        result = self.inspect("CrashLoopBackOff", spec_containers=[
            V1Container(name="app", image="i" * 513, command=["part"] * 17, args=["a" * 4097]),
        ])
        pod = cast(list[dict[str, object]], result["pods"])[0]
        config = cast(list[dict[str, object]], pod["container_execution"])[0]
        self.assertEqual(config["image"], "i" * 512)
        self.assertEqual(config["command"], ["part"] * 16)
        self.assertEqual(config["args"], ["a" * 4096])
        self.assertEqual(config["truncated_fields"], ["image", "command", "args"])

    def test_misleading_database_log_is_not_a_database_failure_class(self) -> None:
        command = ["/bin/sh", "-c"]
        args = ['echo "application starting"; echo "database connection failed"; exit 1']
        result = self.inspect("CrashLoopBackOff", "Error", 1, spec_containers=[
            V1Container(name="app", image="example/app:test", command=command, args=args),
        ])
        core = Mock()
        core.read_namespaced_pod_log.return_value = "application starting\ndatabase connection failed\n"
        with patch.object(service, "core", core):
            logs = service.get_pod_logs("sandbox", "demo-pod", "app", previous=True)
        self.assertIn("database connection failed", str(logs["logs"]))
        self.assertEqual(result["failure_class"], "CrashLoopBackOff")
        self.assertIsNone(result["failure_signal"])
        self.assertFalse(result["diagnosis_included"])
        self.assertTrue(result["logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [
            {"pod": "demo-pod", "container": "app", "previous": True},
        ])
        pod = cast(list[dict[str, object]], result["pods"])[0]
        status = cast(list[dict[str, object]], pod["containers"])[0]
        self.assertEqual(cast(dict[str, object], status["last_termination"])["exit_code"], 1)
        config = cast(list[dict[str, object]], pod["container_execution"])[0]
        self.assertEqual(config["command"], command)
        self.assertEqual(config["args"], args)

    def test_image_pull_classes_preserve_existing_reason(self) -> None:
        for reason in ("ImagePullBackOff", "ErrImagePull"):
            with self.subTest(reason=reason):
                result = self.inspect(reason)
                self.assertEqual(result["failure_class"], reason)
                self.assertEqual(result["primary_failure_reason"], reason)
                self.assertTrue(result["evidence_sufficient"])
                self.assertFalse(result["logs_recommended"])
                self.assertFalse(result["previous_logs_recommended"])
                self.assertEqual(result["recommended_log_targets"], [])

    def test_crash_loop_class_surfaces_behind_generic_error(self) -> None:
        result = self.inspect("CrashLoopBackOff", "Error", 1)
        self.assertEqual(result["primary_failure_reason"], "Error")
        self.assertEqual(result["failure_class"], "CrashLoopBackOff")
        self.assertIsNone(result["failure_signal"])
        self.assertTrue(result["logs_recommended"])
        self.assertTrue(result["previous_logs_recommended"])
        self.assertEqual(
            result["recommended_log_targets"],
            [{"pod": "demo-pod", "container": "app", "previous": True}],
        )
        pod = cast(list[dict[str, object]], result["pods"])[0]
        container = cast(list[dict[str, object]], pod["containers"])[0]
        self.assertEqual(container["reason"], "CrashLoopBackOff")
        termination = cast(dict[str, object], container["last_termination"])
        self.assertEqual(termination["exit_code"], 1)

    def test_post_start_event_suppresses_generic_crash_logs(self) -> None:
        command = ["/bin/sh", "-c", "php artisan migrate --force"]
        result = self.inspect(
            "CrashLoopBackOff", "Error", 137,
            hook_event_pod="demo-pod",
            post_start_command=command,
        )
        self.assertEqual(result["failure_class"], "CrashLoopBackOff")
        self.assertEqual(result["primary_failure_reason"], "Error")
        self.assertEqual(result["failure_signal"], "FailedPostStartHook")
        self.assertTrue(result["evidence_sufficient"])
        self.assertFalse(result["logs_recommended"])
        self.assertFalse(result["previous_logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])
        self.assertEqual(
            result["lifecycle"],
            [{
                "pod": "demo-pod",
                "container": "app",
                "post_start": {"exec": {"command": command}},
            }],
        )
        events = cast(list[dict[str, object]], result["events"])
        self.assertEqual(
            {event["reason"] for event in events},
            {"FailedPostStartHook", "Killing"},
        )

    def test_unrelated_post_start_event_does_not_override_crash_routing(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "Error", 1,
            hook_event_pod="old-pod",
            post_start_command=["/bin/sh", "-c", "echo ready"],
        )
        self.assertIsNone(result["failure_signal"])
        self.assertNotIn("lifecycle", result)
        self.assertTrue(result["logs_recommended"])
        self.assertEqual(
            result["recommended_log_targets"],
            [{"pod": "demo-pod", "container": "app", "previous": True}],
        )

    def test_post_start_event_does_not_hide_another_crashing_container(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "Error", 1,
            other_statuses=[container_status("CrashLoopBackOff", "Error", 1, "python")],
            hook_event_pod="demo-pod",
            post_start_command=["/bin/sh", "-c", "echo ready"],
        )
        self.assertIsNone(result["failure_signal"])
        self.assertTrue(result["logs_recommended"])
        self.assertEqual(
            result["recommended_log_targets"],
            [{"pod": "demo-pod", "container": "app", "previous": True}],
        )

    def test_oom_reason_keeps_priority_over_post_start_event(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "OOMKilled", 137,
            hook_event_pod="demo-pod",
        )
        self.assertEqual(result["failure_class"], "OOMKilled")
        self.assertIsNone(result["failure_signal"])
        self.assertFalse(result["logs_recommended"])

    def test_oomkilled_class_uses_last_termination(self) -> None:
        result = self.inspect("CrashLoopBackOff", "OOMKilled", 137)
        self.assertEqual(result["primary_failure_reason"], "OOMKilled")
        self.assertEqual(result["failure_class"], "OOMKilled")
        self.assertTrue(result["evidence_sufficient"])
        self.assertFalse(result["logs_recommended"])
        self.assertFalse(result["previous_logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])

    def test_two_oomkilled_containers_do_not_recommend_logs(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "OOMKilled", 137,
            other_statuses=[container_status("CrashLoopBackOff", "OOMKilled", 137, "python")],
        )
        self.assertEqual(result["failure_class"], "OOMKilled")
        self.assertTrue(result["evidence_sufficient"])
        self.assertFalse(result["logs_recommended"])
        self.assertFalse(result["previous_logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])

    def test_log_target_excludes_unrelated_container(self) -> None:
        unrelated = SimpleNamespace(
            name="sidecar", image="sidecar:1", ready=True, restart_count=0,
            state=SimpleNamespace(running=SimpleNamespace(), waiting=None, terminated=None),
            last_state=None,
        )
        result = self.inspect("CrashLoopBackOff", "Error", 1, other_statuses=[unrelated])
        self.assertEqual(
            result["recommended_log_targets"],
            [{"pod": "demo-pod", "container": "app", "previous": True}],
        )

    def test_oom_with_secondary_error_keeps_oom_fast_path(self) -> None:
        with patch.object(
            service, "normalized_failure_class", wraps=service.normalized_failure_class
        ) as classify:
            result = self.inspect(
                "CrashLoopBackOff", "OOMKilled", 137,
                other_statuses=[container_status("CrashLoopBackOff", "Error", 1, "python")],
            )
        classify.assert_called_once()
        self.assertEqual(result["failure_class"], "OOMKilled")
        self.assertTrue(result["evidence_sufficient"])
        self.assertFalse(result["logs_recommended"])
        self.assertFalse(result["previous_logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])

    def test_two_crashing_containers_start_with_one_log_target(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "Error", 1,
            other_statuses=[container_status("CrashLoopBackOff", "Error", 1, "python")],
        )
        self.assertEqual(
            result["recommended_log_targets"],
            [{"pod": "demo-pod", "container": "app", "previous": True}],
        )

    def test_crash_with_oom_sidecar_targets_only_crashing_container(self) -> None:
        result = self.inspect(
            "CrashLoopBackOff", "Error", 1,
            other_statuses=[container_status("CrashLoopBackOff", "OOMKilled", 137, "python")],
        )
        self.assertEqual(result["failure_class"], "CrashLoopBackOff")
        self.assertTrue(result["logs_recommended"])
        self.assertEqual(
            result["recommended_log_targets"],
            [{"pod": "demo-pod", "container": "app", "previous": True}],
        )

    def test_unclassified_terminated_error_does_not_speculate_logs(self) -> None:
        status = SimpleNamespace(
            name="app", image="app:1", ready=False, restart_count=0,
            state=SimpleNamespace(
                running=None, waiting=None,
                terminated=SimpleNamespace(reason="Error", message=None, exit_code=1),
            ),
            last_state=None,
        )
        result = self.inspect("Error", primary_status=status)
        self.assertIsNone(result["failure_class"])
        self.assertFalse(result["logs_recommended"])
        self.assertFalse(result["previous_logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])

    def test_stale_oom_does_not_override_current_error(self) -> None:
        result = self.inspect("Error", "OOMKilled", 137)
        self.assertEqual(result["primary_failure_reason"], "Error")
        self.assertIsNone(result["failure_class"])
        self.assertFalse(result["logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])

    def test_failed_scheduling_class_uses_existing_event(self) -> None:
        result = self.inspect("ContainerCreating", phase="Pending", scheduling=True)
        self.assertEqual(result["primary_failure_reason"], "FailedScheduling")
        self.assertEqual(result["failure_class"], "FailedScheduling")
        self.assertFalse(result["logs_available"])
        self.assertFalse(result["logs_recommended"])
        self.assertFalse(result["previous_logs_recommended"])
        self.assertEqual(result["recommended_log_targets"], [])

    def test_unknown_class_is_not_guessed(self) -> None:
        result = self.inspect("SomeUnknownReason")
        self.assertEqual(result["primary_failure_reason"], "SomeUnknownReason")
        self.assertIsNone(result["failure_class"])

    def test_tool_input_schemas_and_names_are_unchanged(self) -> None:
        tools = asyncio.run(MCP.list_tools())
        self.assertEqual(
            {tool.name: tool.input_schema for tool in tools},
            {
                "inspect_deployment_health": {
                    "properties": {
                        "namespace": {"title": "Namespace", "type": "string"},
                        "name": {"title": "Name", "type": "string"},
                        "event_limit": {"default": 8, "title": "Event Limit", "type": "integer"},
                    },
                    "required": ["namespace", "name"],
                    "title": "inspect_deployment_healthArguments",
                    "type": "object",
                },
                "find_unhealthy_deployments": {
                    "properties": {
                        "namespace": {"title": "Namespace", "type": "string"},
                        "limit": {"default": 20, "title": "Limit", "type": "integer"},
                    },
                    "required": ["namespace"],
                    "title": "find_unhealthy_deploymentsArguments",
                    "type": "object",
                },
                "get_pod_logs": {
                    "properties": {
                        "namespace": {"title": "Namespace", "type": "string"},
                        "name": {"title": "Name", "type": "string"},
                        "container": {"default": "", "title": "Container", "type": "string"},
                        "tail_lines": {
                            "default": 100,
                            "maximum": 500,
                            "minimum": 1,
                            "title": "Tail Lines",
                            "type": "integer",
                        },
                        "previous": {"default": False, "title": "Previous", "type": "boolean"},
                    },
                    "required": ["namespace", "name"],
                    "title": "get_pod_logsArguments",
                    "type": "object",
                },
                "resolve_workloads": {
                    "properties": {
                        "namespace": {"minLength": 1, "title": "Namespace", "type": "string"},
                        "kind": {
                            "enum": ["Deployment", "StatefulSet", "DaemonSet", "Pod"],
                            "title": "Kind",
                            "type": "string",
                        },
                        "pattern": {"minLength": 1, "title": "Pattern", "type": "string"},
                        "match_type": {
                            "enum": [
                                "exact", "prefix", "glob", "substring", "token_match",
                                "label_selector", "auto",
                            ],
                            "title": "Match Type",
                            "type": "string",
                        },
                    },
                    "required": ["namespace", "kind", "pattern", "match_type"],
                    "title": "resolve_workloadsArguments",
                    "type": "object",
                },
                "search_runbooks": {
                    "properties": {
                        "query": {"title": "Query", "type": "string"},
                        "limit": {"default": 5, "title": "Limit", "type": "integer"},
                    },
                    "required": ["query"],
                    "title": "search_runbooksArguments",
                    "type": "object",
                },
            },
        )
        self.assertTrue(all(len(tool.description or "") < 180 for tool in tools))

    def test_log_tool_validates_bounds_and_keeps_session_usable(self) -> None:
        async def run_inline(fn: Callable[[], object]) -> object:
            return fn()

        async def check() -> None:
            with (
                patch("tools.kubernetes.service.get_pod_logs", return_value={"ok": True}) as read_logs,
                patch(
                    "mcp.server.mcpserver.utilities.func_metadata.anyio.to_thread.run_sync",
                    new=run_inline,
                ),
            ):
                async with Client(MCP, mode="legacy") as client:
                    for invalid in (0, 501):
                        result = await client.call_tool(
                            "get_pod_logs",
                            {"namespace": "sandbox", "name": "demo-pod", "tail_lines": invalid},
                        )
                        self.assertTrue(result.is_error)
                        self.assertIn("validation error", str(result.content))
                        self.assertIn("tail_lines", str(result.content))
                        read_logs.assert_not_called()

                    for valid in (1, 500):
                        result = await client.call_tool(
                            "get_pod_logs",
                            {"namespace": "sandbox", "name": "demo-pod", "tail_lines": valid},
                        )
                        self.assertFalse(result.is_error)

                self.assertEqual(read_logs.call_count, 2)
                self.assertEqual(
                    [call.args[3] for call in read_logs.call_args_list],
                    [1, 500],
                )

        asyncio.run(check())

    def test_log_service_retains_defensive_bounds(self) -> None:
        with patch.object(service, "core") as core:
            for invalid in (0, 501):
                with self.subTest(tail_lines=invalid), self.assertRaises(ValueError):
                    service.get_pod_logs("sandbox", "demo-pod", tail_lines=invalid)
            core.read_namespaced_pod_log.assert_not_called()

    def test_skills_keep_distinct_investigation_scopes(self) -> None:
        skill_root = Path(__file__).parents[1] / "skills"
        service_skill = (
            skill_root / "kubernetes-service-investigations/SKILL.md"
        ).read_text()
        namespace_skill = (
            skill_root / "kubernetes-namespace-investigation/SKILL.md"
        ).read_text()

        self.assertIn("name: kubernetes-service-investigation", service_skill)
        self.assertIn("## Scope Resolution", service_skill)
        self.assertIn("recommended_log_targets", service_skill)
        self.assertIn("name: kubernetes-namespace-investigation", namespace_skill)
        self.assertIn("find_unhealthy_deployments", namespace_skill)
        self.assertIn("inspect_deployment_health", namespace_skill)
        self.assertIn("## Stop and Report", namespace_skill)


if __name__ == "__main__":
    unittest.main()
