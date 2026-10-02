from mcp.server import MCPServer

from prompts.common import parse_bool, render_prompt


def register_kubernetes_prompts(mcp: MCPServer) -> None:
    @mcp.prompt()
    async def kubernetes_service_investigation(
        namespace: str,
        deployment: str,
        use_runbook: str = "false",
    ) -> str:
        """Generate an efficient, read-only Deployment investigation prompt."""
        include_runbook = parse_bool(use_runbook, "use_runbook")
        return render_prompt(
            "kubernetes_service_investigation.md",
            namespace=namespace,
            deployment=deployment,
            use_runbook=include_runbook,
        )

    @mcp.prompt()
    async def namespace_health_review(
        namespace: str,
        include_logs: str = "false",
    ) -> str:
        """Generate an efficient, read-only health review for workloads in a Kubernetes namespace."""
        include_logs_enabled = parse_bool(include_logs, "include_logs")
        return render_prompt(
            "namespace_health_review.md",
            namespace=namespace,
            include_logs=include_logs_enabled,
        )
