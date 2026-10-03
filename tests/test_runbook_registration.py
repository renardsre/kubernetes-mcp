import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import StrictUndefined, UndefinedError
from mcp import Client
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, CompletionArgument, ResourceTemplateReference

from mcp_server import create_mcp_server
from prompts.common import _TEMPLATE_ENV, parse_bool, render_prompt
from resources.kubernetes import (
    complete_runbook_slug,
    get_runbook_catalog_resource,
    get_runbook_resource,
)

SERVER_PATH = Path(__file__).parents[1] / "server.py"
SERVER = SimpleNamespace(mcp=create_mcp_server())


class RunbookRegistrationTests(unittest.TestCase):
    def test_tools_and_resource_template_are_registered(self) -> None:
        async def check() -> None:
            tools = await SERVER.mcp.list_tools()
            names = {tool.name for tool in tools}
            self.assertEqual(
                names,
                {
                    "inspect_deployment_health",
                    "find_unhealthy_deployments",
                    "get_pod_logs",
                    "resolve_workloads",
                    "search_runbooks",
                },
            )

            templates = await SERVER.mcp.list_resource_templates()
            self.assertEqual(
                {template.uri_template for template in templates},
                {"k8s://runbooks/{slug}"},
            )

            resources = await SERVER.mcp.list_resources()
            self.assertEqual(
                {str(resource.uri) for resource in resources},
                {"k8s://runbooks"},
            )

        asyncio.run(check())

    def test_resource_handler_loads_runbook_content(self) -> None:
        self.assertIn(
            "# ImagePullBackOff",
            asyncio.run(get_runbook_resource("imagepullbackoff")),
        )

    def test_resource_handler_rejects_unknown_slug(self) -> None:
        with self.assertRaises(ResourceNotFoundError):
            asyncio.run(get_runbook_resource("not-a-runbook"))

    def test_catalog_resource_returns_all_runbooks(self) -> None:
        catalog = asyncio.run(get_runbook_catalog_resource())
        self.assertEqual(len(catalog), 11)
        self.assertEqual(catalog[0]["slug"], "00-service-triage")
        self.assertNotIn("file", catalog[0])
        self.assertNotIn("keywords", catalog[0])

        async def read() -> object:
            async with Client(SERVER.mcp, mode="legacy") as client:
                result = await client.read_resource("k8s://runbooks")
                return result.contents[0]

        self.assertIn("00-service-triage", str(asyncio.run(read())))

    def test_resource_completion_returns_matching_slugs(self) -> None:
        async def complete(prefix: str) -> list[str]:
            result = await complete_runbook_slug(
                ResourceTemplateReference(uri="k8s://runbooks/{slug}"),
                CompletionArgument(name="slug", value=prefix),
                None,
            )
            if result is None:
                self.fail("runbook completion did not return a result")
            return result.values

        self.assertEqual(asyncio.run(complete("o")), ["oomkilled"])
        self.assertEqual(asyncio.run(complete("image")), ["imagepullbackoff"])

    def test_investigation_prompt_registration_and_arguments(self) -> None:
        prompts = asyncio.run(SERVER.mcp.list_prompts())
        self.assertEqual(
            {item.name for item in prompts},
            {"kubernetes_service_investigation", "namespace_health_review"},
        )
        self.assertEqual(
            sum(
                item.name == "kubernetes_service_investigation"
                for item in prompts
            ),
            1,
        )
        prompt = next(
            item
            for item in prompts
            if item.name == "kubernetes_service_investigation"
        )
        self.assertEqual(
            {arg.name: arg.required for arg in prompt.arguments},
            {
                "namespace": True,
                "deployment": True,
                "use_runbook": False,
            },
        )
        self.assertEqual(
            prompt.description,
            "Generate an efficient, read-only Deployment investigation prompt.",
        )

    def test_investigation_prompt_template_loads_and_requires_variables(self) -> None:
        template = _TEMPLATE_ENV.get_template(
            "kubernetes_service_investigation.md"
        )
        self.assertIn(
            "{{ namespace }}",
            (SERVER_PATH.parent / "prompts/templates/kubernetes_service_investigation.md")
            .read_text(encoding="utf-8"),
        )
        self.assertIs(_TEMPLATE_ENV.undefined, StrictUndefined)
        self.assertFalse(_TEMPLATE_ENV.autoescape)
        self.assertTrue(_TEMPLATE_ENV.trim_blocks)
        self.assertTrue(_TEMPLATE_ENV.lstrip_blocks)
        arguments = {
            "namespace": "sandbox",
            "deployment": "holmes-broken",
            "use_runbook": False,
        }
        for missing in arguments:
            with self.subTest(missing=missing), self.assertRaises(UndefinedError):
                template.render(**{
                    key: value
                    for key, value in arguments.items()
                    if key != missing
                })

    def test_investigation_prompt_exact_rendered_text(self) -> None:
        base_text = (
            "Investigate Deployment holmes-broken in namespace sandbox.\n\n"
            "Use available Kubernetes evidence to describe its health and observed failure mechanism.\n\n"
            "Summarize the established cause, supporting evidence, and recommended next action.\n\n"
        )
        runbook_text = (
            "Include relevant runbook guidance when available. Identify the runbook title and URI, and distinguish a runbook that was read from one that was only discovered.\n"
        )
        for use_runbook, expected in (
            ("false", base_text + "\nDo not make changes."),
            ("true", base_text + runbook_text + "\nDo not make changes."),
        ):
            with self.subTest(use_runbook=use_runbook):
                result = asyncio.run(
                    SERVER.mcp.get_prompt(
                        "kubernetes_service_investigation",
                        {
                            "namespace": "sandbox",
                            "deployment": "holmes-broken",
                            "use_runbook": use_runbook,
                        },
                    )
                )
                self.assertEqual(len(result.messages), 1)
                self.assertEqual(result.messages[0].role, "user")
                self.assertEqual(result.messages[0].content.text, expected)

        default_result = asyncio.run(
            SERVER.mcp.get_prompt(
                "kubernetes_service_investigation",
                {"namespace": "sandbox", "deployment": "holmes-broken"},
            )
        )
        self.assertEqual(
            default_result.messages[0].content.text,
            base_text + "\nDo not make changes.",
        )

    def test_investigation_prompt_requires_namespace_and_deployment(self) -> None:
        for arguments in ({"deployment": "holmes-broken"}, {"namespace": "sandbox"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                asyncio.run(
                    SERVER.mcp.get_prompt(
                        "kubernetes_service_investigation", arguments
                    )
                )

    def test_investigation_prompt_rejects_invalid_runbook_value(self) -> None:
        with self.assertRaisesRegex(MCPError, "use_runbook must be") as error:
            asyncio.run(
                SERVER.mcp.get_prompt(
                    "kubernetes_service_investigation",
                    {
                        "namespace": "sandbox",
                        "deployment": "holmes-broken",
                        "use_runbook": "maybe",
                    },
                )
            )
        self.assertEqual(error.exception.code, INVALID_PARAMS)

    def test_shared_prompt_helpers(self) -> None:
        self.assertTrue(parse_bool(" TRUE ", "include_logs"))
        self.assertFalse(parse_bool("False", "include_logs"))
        with self.assertRaisesRegex(MCPError, "include_logs must be") as error:
            parse_bool("maybe", "include_logs")
        self.assertEqual(error.exception.code, INVALID_PARAMS)

        self.assertIn(
            "namespace sandbox",
            render_prompt(
                "namespace_health_review.md",
                namespace="sandbox",
                include_logs=False,
            ),
        )
        with self.assertRaises(UndefinedError):
            render_prompt("namespace_health_review.md", include_logs=False)

    def test_namespace_health_prompt_registration_and_arguments(self) -> None:
        prompts = asyncio.run(SERVER.mcp.list_prompts())
        self.assertEqual(
            sum(item.name == "namespace_health_review" for item in prompts),
            1,
        )
        prompt = next(item for item in prompts if item.name == "namespace_health_review")
        self.assertEqual(
            {arg.name: arg.required for arg in prompt.arguments},
            {"namespace": True, "include_logs": False},
        )
        self.assertEqual(
            prompt.description,
            "Generate an efficient, read-only health review for workloads in a Kubernetes namespace.",
        )

    def test_namespace_health_prompt_exact_rendered_text(self) -> None:
        base_text = (
            "Review the health of workloads in namespace sandbox.\n\n"
            "Use available Kubernetes evidence to summarize observed unhealthy workloads and their failure mechanisms.\n\n"
        )
        ending = (
            "Summarize:\n"
            "- unhealthy workload\n"
            "- observed failure\n"
            "- supporting evidence\n"
            "- recommended next action\n\n"
            "Do not make changes."
        )
        log_guidance = (
            "Include relevant runtime log findings in the summary if they are already available.\n\n"
        )
        for include_logs, expected in (
            ("false", base_text + "\n" + ending),
            ("TRUE", base_text + log_guidance + ending),
        ):
            with self.subTest(include_logs=include_logs):
                result = asyncio.run(
                    SERVER.mcp.get_prompt(
                        "namespace_health_review",
                        {"namespace": "sandbox", "include_logs": include_logs},
                    )
                )
                self.assertEqual(len(result.messages), 1)
                self.assertEqual(result.messages[0].role, "user")
                self.assertEqual(result.messages[0].content.text, expected)

        default_result = asyncio.run(
            SERVER.mcp.get_prompt("namespace_health_review", {"namespace": "sandbox"})
        )
        self.assertEqual(default_result.messages[0].content.text, base_text + "\n" + ending)
        self.assertNotIn("runtime log findings", default_result.messages[0].content.text)

    def test_namespace_health_prompt_requires_namespace(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(SERVER.mcp.get_prompt("namespace_health_review", {}))

    def test_namespace_health_prompt_rejects_invalid_logs_value(self) -> None:
        with self.assertRaisesRegex(MCPError, "include_logs must be") as error:
            asyncio.run(
                SERVER.mcp.get_prompt(
                    "namespace_health_review",
                    {"namespace": "sandbox", "include_logs": "maybe"},
                )
            )
        self.assertEqual(error.exception.code, INVALID_PARAMS)


if __name__ == "__main__":
    unittest.main()
