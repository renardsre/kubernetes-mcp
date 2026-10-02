from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from resources.catalog import search_runbook_catalog
from services import kubernetes as service


def register_kubernetes_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    def inspect_deployment_health(
        namespace: str,
        name: str,
        event_limit: int = 8,
    ) -> dict[str, object]:
        """Return bounded health evidence for a known Deployment; use it first when the name is known. The result indicates when runtime logs may help."""
        return service.inspect_deployment_health(namespace, name, event_limit)

    @mcp.tool()
    def find_unhealthy_deployments(
        namespace: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Discover unhealthy Deployments in a namespace; use inspect_deployment_health for detailed evidence."""
        return service.find_unhealthy_deployments(namespace, limit)

    @mcp.tool()
    def get_pod_logs(
        namespace: str,
        name: str,
        container: str = "",
        tail_lines: Annotated[int, Field(ge=1, le=500)] = 100,
        previous: bool = False,
    ) -> dict[str, object]:
        """Return bounded pod runtime logs; previous=True reads a prior container execution."""
        return service.get_pod_logs(namespace, name, container, tail_lines, previous)

    @mcp.tool()
    async def search_runbooks(
        query: str,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        """Search runbook metadata by failure class or symptom, not Deployment or namespace name."""
        return [dict(result) for result in search_runbook_catalog(query, limit)]
