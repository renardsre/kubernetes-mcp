from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp_types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    ResourceTemplateReference,
)

from capability_metadata import capability_meta
from resources.catalog import (
    complete_runbook_slugs,
    list_runbook_catalog,
    load_runbook,
)


async def get_runbook_catalog_resource() -> list[dict[str, object]]:
    """Return discoverable runbook metadata without Markdown content."""
    return [dict(entry) for entry in list_runbook_catalog()]


async def get_runbook_resource(slug: str) -> str:
    """Return Markdown for one runbook explicitly listed in the catalog."""
    try:
        return load_runbook(slug)
    except ValueError as exc:
        raise ResourceNotFoundError(str(exc)) from exc


async def complete_runbook_slug(
    ref: ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    """Complete the slug variable in the runbook resource template."""
    del context
    if (
        not isinstance(ref, ResourceTemplateReference)
        or ref.uri != "k8s://runbooks/{slug}"
        or argument.name != "slug"
    ):
        return None

    values = complete_runbook_slugs(argument.value)
    return Completion(values=values, total=len(values), has_more=False)


def register_kubernetes_resources(mcp: MCPServer) -> None:
    mcp.resource(
        "k8s://runbooks",
        name="kubernetes-runbook-catalog",
        description="A concise catalog of bundled Kubernetes runbooks.",
        mime_type="application/json",
        meta=capability_meta("workflow_discovery"),
    )(get_runbook_catalog_resource)

    mcp.resource(
        "k8s://runbooks/{slug}",
        name="kubernetes-runbook",
        description="A bundled Kubernetes troubleshooting runbook.",
        mime_type="text/markdown",
        meta=capability_meta("workflow_consume"),
    )(get_runbook_resource)

    mcp.completion()(complete_runbook_slug)
