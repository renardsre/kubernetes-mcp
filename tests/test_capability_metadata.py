import asyncio
import unittest

from mcp import Client

from capability_metadata import CAPABILITY_META_KEY, capability_meta
from mcp_server import create_mcp_server


class CapabilityMetadataTests(unittest.TestCase):
    def test_contract_is_domain_neutral_and_versioned(self) -> None:
        self.assertEqual(
            capability_meta("action", "generic_raw"),
            {
                CAPABILITY_META_KEY: {
                    "version": 1,
                    "role": "action",
                    "fallback_level": "generic_raw",
                }
            },
        )

    def test_capabilities_expose_roles_on_mcp_lists(self) -> None:
        async def inspect() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
            async with Client(create_mcp_server(), mode="legacy") as client:
                tools = await client.list_tools()
                resources = await client.list_resources()
                templates = await client.list_resource_templates()
                return (
                    {tool.name: tool.meta for tool in tools.tools},
                    {str(resource.uri): resource.meta for resource in resources.resources},
                    {
                        template.uri_template: template.meta
                        for template in templates.resource_templates
                    },
                )

        tools, resources, templates = asyncio.run(inspect())
        self.assertEqual(
            tools,
            {
                "resolve_workloads": capability_meta("evidence"),
                "inspect_deployment_health": capability_meta("evidence"),
                "find_unhealthy_deployments": capability_meta("evidence"),
                "get_pod_logs": capability_meta("evidence"),
                "search_runbooks": capability_meta("workflow_discovery"),
            },
        )
        self.assertEqual(resources, {"k8s://runbooks": capability_meta("workflow_discovery")})
        self.assertEqual(
            templates,
            {"k8s://runbooks/{slug}": capability_meta("workflow_consume")},
        )
