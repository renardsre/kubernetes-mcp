import asyncio
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from kubernetes.client.exceptions import ApiException

from mcp_server import create_mcp_server
from services import kubernetes as service


def workload(name: str) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def match_names(result: dict[str, object]) -> list[object]:
    return [item["name"] for item in cast(list[dict[str, object]], result["matches"])]


class ResolveWorkloadsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.apps = Mock()
        self.core = Mock()
        self.apps.list_namespaced_deployment.return_value = SimpleNamespace(items=[])
        self.apps.list_namespaced_stateful_set.return_value = SimpleNamespace(items=[])
        self.apps.list_namespaced_daemon_set.return_value = SimpleNamespace(items=[])
        self.core.list_namespaced_pod.return_value = SimpleNamespace(items=[])
        apps_patch = patch.object(service, "apps", self.apps)
        core_patch = patch.object(service, "core", self.core)
        apps_patch.start()
        core_patch.start()
        self.addCleanup(apps_patch.stop)
        self.addCleanup(core_patch.stop)

    def test_exact_match(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("holmes-api"), workload("holmes-api-worker")
        ]
        result = service.resolve_workloads("sandbox", "Deployment", "holmes-api", "exact")
        self.assertEqual(result, {
            "requested_pattern": "holmes-api",
            "namespace": "sandbox",
            "kind": "Deployment",
            "match_type": "exact",
            "match_count": 1,
            "matches": [{
                "name": "holmes-api",
                "kind": "Deployment",
                "namespace": "sandbox",
                "match_method": "exact",
                "match_reason": "name equals pattern",
            }],
            "resolved": True,
            "truncated": False,
        })
        self.apps.list_namespaced_deployment.assert_called_once_with(namespace="sandbox")

    def test_no_exact_match(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [workload("other")]
        result = service.resolve_workloads("sandbox", "Deployment", "holmes-api", "exact")
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["match_count"], 0)
        self.assertFalse(result["resolved"])

    def test_prefix_match(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("holmes-api-worker"), workload("holmes-api"), workload("other")
        ]
        result = service.resolve_workloads("sandbox", "Deployment", "holmes-api", "prefix")
        self.assertEqual(
            match_names(result),
            ["holmes-api", "holmes-api-worker"],
        )
        self.assertFalse(result["resolved"])

    def test_glob_single_match(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("api-ab"), workload("api-abc")
        ]
        result = service.resolve_workloads("sandbox", "Deployment", "api-??", "glob")
        self.assertEqual(match_names(result), ["api-ab"])
        self.assertTrue(result["resolved"])

    def test_glob_multiple_matches_are_sorted(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("holmes-crash-z"), workload("holmes-crash-a"), workload("unrelated")
        ]
        result = service.resolve_workloads("sandbox", "Deployment", "holmes-crash*", "glob")
        self.assertEqual(
            match_names(result),
            ["holmes-crash-a", "holmes-crash-z"],
        )
        self.assertEqual(result["match_count"], 2)
        self.assertFalse(result["resolved"])

    def test_glob_no_matches(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [workload("api")]
        result = service.resolve_workloads("sandbox", "Deployment", "*worker", "glob")
        self.assertEqual(result["matches"], [])
        self.assertFalse(result["resolved"])

    def test_substring_match(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("kraken-api-and-dashboard"), workload("other")
        ]
        result = service.resolve_workloads("development", "Deployment", "dashboard", "substring")
        self.assertEqual(match_names(result), ["kraken-api-and-dashboard"])
        self.assertEqual(
            cast(list[dict[str, object]], result["matches"])[0]["match_method"],
            "substring",
        )
        self.assertTrue(result["resolved"])

    def test_token_match_returns_all_plausible_names(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("kraken-api-and-dashboard"), workload("kraken-dashboard-api"),
        ]
        result = service.resolve_workloads(
            "development", "Deployment", "kraken-dashboard", "token_match"
        )
        self.assertEqual(
            match_names(result),
            ["kraken-dashboard-api", "kraken-api-and-dashboard"],
        )
        self.assertEqual(result["match_count"], 2)
        self.assertFalse(result["resolved"])
        self.assertEqual(
            [item["match_method"] for item in cast(list[dict[str, object]], result["matches"])],
            ["prefix", "token_match"],
        )
        self.assertTrue(all(
            isinstance(item["match_reason"], str)
            for item in cast(list[dict[str, object]], result["matches"])
        ))

    def test_token_match_accepts_incomplete_name_tokens(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("kraken-api-and-dashboard"), workload("kraken-dashboard-api"),
        ]
        result = service.resolve_workloads(
            "development", "Deployment", "kraken-dash", "token_match"
        )
        self.assertEqual(result["match_count"], 2)
        self.assertFalse(result["resolved"])

    def test_auto_uses_all_methods_without_first_hit_selection(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("kraken-api-and-dashboard"), workload("kraken-dashboard-api"),
        ]
        result = service.resolve_workloads("development", "Deployment", "kraken-dashboard", "auto")
        self.assertEqual(
            match_names(result),
            ["kraken-dashboard-api", "kraken-api-and-dashboard"],
        )
        self.assertFalse(result["resolved"])

    def test_auto_resolves_only_one_candidate(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("kraken-api-and-dashboard"), workload("unrelated"),
        ]
        result = service.resolve_workloads("development", "Deployment", "kraken-dashboard", "auto")
        self.assertEqual(match_names(result), ["kraken-api-and-dashboard"])
        self.assertTrue(result["resolved"])

    def test_auto_exact_does_not_hide_other_plausible_names(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [
            workload("kraken-dashboard"), workload("kraken-dashboard-api"),
        ]
        result = service.resolve_workloads("development", "Deployment", "kraken-dashboard", "auto")
        self.assertEqual(match_names(result), ["kraken-dashboard", "kraken-dashboard-api"])
        self.assertFalse(result["resolved"])

    def test_auto_no_matches(self) -> None:
        self.apps.list_namespaced_deployment.return_value.items = [workload("unrelated")]
        result = service.resolve_workloads("development", "Deployment", "kraken-dashboard", "auto")
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["match_count"], 0)
        self.assertFalse(result["resolved"])

    def test_namespace_isolation(self) -> None:
        self.core.list_namespaced_pod.return_value.items = [workload("api-pod")]
        service.resolve_workloads("sandbox", "Pod", "api", "prefix")
        self.core.list_namespaced_pod.assert_called_once_with(namespace="sandbox")
        self.apps.list_namespaced_deployment.assert_not_called()

    def test_kind_isolation(self) -> None:
        for kind, method in (
            ("Deployment", self.apps.list_namespaced_deployment),
            ("StatefulSet", self.apps.list_namespaced_stateful_set),
            ("DaemonSet", self.apps.list_namespaced_daemon_set),
            ("Pod", self.core.list_namespaced_pod),
        ):
            with self.subTest(kind=kind):
                method.return_value.items = [workload("api")]
                result = service.resolve_workloads("sandbox", kind, "api", "exact")
                self.assertEqual(result["match_count"], 1)
                self.assertEqual(cast(list[dict[str, object]], result["matches"])[0]["kind"], kind)
                method.assert_called_once_with(namespace="sandbox")
                method.reset_mock()

    def test_label_selector_uses_server_side_filter(self) -> None:
        self.apps.list_namespaced_stateful_set.return_value.items = [workload("db-b")]
        result = service.resolve_workloads(
            "sandbox", "StatefulSet", "app=database", "label_selector"
        )
        self.apps.list_namespaced_stateful_set.assert_called_once_with(
            namespace="sandbox", label_selector="app=database"
        )
        self.assertEqual(match_names(result), ["db-b"])
        self.assertTrue(result["resolved"])

    def test_invalid_match_type_and_kind_are_rejected_before_api_read(self) -> None:
        for kind, match_type in (("Deployment", "regex"), ("Job", "exact")):
            with self.subTest(kind=kind, match_type=match_type), self.assertRaises(ValueError):
                service.resolve_workloads("sandbox", kind, "api", match_type)
        self.apps.list_namespaced_deployment.assert_not_called()
        self.core.list_namespaced_pod.assert_not_called()

    def test_api_error_is_not_an_empty_match(self) -> None:
        self.apps.list_namespaced_deployment.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        with self.assertRaisesRegex(RuntimeError, "Kubernetes API error 404"):
            service.resolve_workloads("missing", "Deployment", "api", "exact")

    def test_output_is_bounded_without_hiding_match_count(self) -> None:
        self.core.list_namespaced_pod.return_value.items = [
            workload(f"api-{number:03d}") for number in range(101, -1, -1)
        ]
        result = service.resolve_workloads("sandbox", "Pod", "api-", "prefix")
        self.assertEqual(result["match_count"], 102)
        self.assertEqual(len(match_names(result)), 100)
        self.assertEqual(match_names(result)[0], "api-000")
        self.assertTrue(result["truncated"])
        self.assertFalse(result["resolved"])

    def test_mcp_schema_exposes_supported_kinds_and_match_types(self) -> None:
        tools = asyncio.run(create_mcp_server().list_tools())
        resolver = next(tool for tool in tools if tool.name == "resolve_workloads")
        schema = resolver.input_schema
        self.assertEqual(
            set(schema["required"]), {"namespace", "kind", "pattern", "match_type"}
        )
        self.assertEqual(
            schema["properties"]["kind"]["enum"],
            ["Deployment", "StatefulSet", "DaemonSet", "Pod"],
        )
        self.assertEqual(
            schema["properties"]["match_type"]["enum"],
            ["exact", "prefix", "glob", "substring", "token_match", "label_selector", "auto"],
        )


if __name__ == "__main__":
    unittest.main()
