"""Read-only smoke client for the Kubernetes MCP server."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

PROJECT_ROOT = Path(__file__).resolve().parent


async def capability_surface(
    client: Client,
) -> dict[str, list[str]]:
    """Fetch advertised MCP primitive lists for transport comparison."""
    tools = await client.list_tools()
    prompts = await client.list_prompts()
    resources = await client.list_resources()
    templates = await client.list_resource_templates()

    return {
        "tools": sorted(
            item.name
            for item in tools.tools
        ),
        "prompts": sorted(
            item.name
            for item in prompts.prompts
        ),
        "resources": sorted(
            str(item.uri)
            for item in resources.resources
        ),
        "resource_templates": sorted(
            item.uri_template
            for item in templates.resource_templates
        ),
    }


def show_result(
    label: str,
    value: Any,
) -> None:
    """Pretty-print smoke-test output."""
    print(f"\n=== {label} ===")

    if isinstance(value, str):
        print(value)
        return

    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


def extract_runbook_uri(
    structured_content: object,
) -> str | None:
    """Extract the first runbook URI from search_runbooks output."""
    if not isinstance(structured_content, dict):
        return None

    results = structured_content.get("result")

    if not isinstance(results, list) or not results:
        return None

    first_result = results[0]

    if not isinstance(first_result, dict):
        return None

    uri = first_result.get("uri")

    if not isinstance(uri, str) or not uri:
        return None

    return uri


async def smoke(
    client: Client,
    namespace: str,
    deployment: str | None,
) -> None:
    """Run the read-only MCP smoke workflow."""
    server_name = (
        client.server_info.name
        if client.server_info
        else "MCP server"
    )

    print(f"Connected: {server_name}")

    # ------------------------------------------------------------------
    # Capability inventory
    # ------------------------------------------------------------------

    capabilities = await capability_surface(client)

    show_result(
        "CAPABILITIES",
        capabilities,
    )

    # ------------------------------------------------------------------
    # Primary Kubernetes evidence
    # ------------------------------------------------------------------

    if deployment:
        tool_name = "inspect_deployment_health"
        arguments: dict[str, object] = {
            "namespace": namespace,
            "name": deployment,
        }
    else:
        tool_name = "find_unhealthy_deployments"
        arguments = {
            "namespace": namespace,
        }

    workload = await client.call_tool(
        tool_name,
        arguments,
    )

    if workload.is_error:
        target = (
            f"{namespace}/{deployment}"
            if deployment
            else f"namespace {namespace}"
        )

        detail = "; ".join(
            getattr(item, "text", str(item))
            for item in workload.content
        )

        raise RuntimeError(
            f"{tool_name} failed for {target}: {detail}"
        )

    workload_result = (
        workload.structured_content
        or workload.content
    )

    show_result(
        tool_name,
        workload_result,
    )

    # ------------------------------------------------------------------
    # Runbook discovery
    # ------------------------------------------------------------------

    runbook_query = "CrashLoopBackOff"

    if (
        deployment
        and isinstance(
            workload.structured_content,
            dict,
        )
    ):
        failure_class = (
            workload.structured_content.get(
                "failure_class"
            )
        )

        if (
            isinstance(failure_class, str)
            and failure_class
        ):
            runbook_query = failure_class

    runbooks = await client.call_tool(
        "search_runbooks",
        {
            "query": runbook_query,
            "limit": 3,
        },
    )

    if runbooks.is_error:
        raise RuntimeError(
            f"search_runbooks failed: "
            f"{runbooks.content}"
        )

    runbook_result = (
        runbooks.structured_content
        or runbooks.content
    )

    show_result(
        f"search_runbooks ({runbook_query})",
        runbook_result,
    )

    # ------------------------------------------------------------------
    # Selected runbook Resource read
    # ------------------------------------------------------------------

    runbook_uri = extract_runbook_uri(
        runbooks.structured_content
    )

    if runbook_uri is None:
        raise RuntimeError(
            f"search_runbooks({runbook_query!r}) "
            "returned no readable runbook URI"
        )

    selected_runbook = await client.read_resource(
        runbook_uri
    )

    if not selected_runbook.contents:
        raise RuntimeError(
            f"{runbook_uri} returned no content"
        )

    runbook_text = getattr(
        selected_runbook.contents[0],
        "text",
        None,
    )

    if not isinstance(runbook_text, str):
        raise TypeError(
            f"{runbook_uri} did not return text content"
        )

    show_result(
        f"RUNBOOK BODY — {runbook_uri}",
        runbook_text,
    )

    # ------------------------------------------------------------------
    # Prompt retrieval
    # ------------------------------------------------------------------

    if deployment:
        prompt_name = (
            "kubernetes_service_investigation"
        )

        prompt_args = {
            "namespace": namespace,
            "deployment": deployment,
        }
    else:
        prompt_name = (
            "namespace_health_review"
        )

        prompt_args = {
            "namespace": namespace,
        }

    prompt = await client.get_prompt(
        prompt_name,
        prompt_args,
    )

    show_result(
        prompt_name,
        [
            message.model_dump(
                mode="json"
            )
            for message in prompt.messages
        ],
    )

    # ------------------------------------------------------------------
    # Static runbook catalog Resource
    # ------------------------------------------------------------------

    catalog = await client.read_resource(
        "k8s://runbooks"
    )

    if not catalog.contents:
        raise RuntimeError(
            "k8s://runbooks returned no content"
        )

    catalog_text = getattr(
        catalog.contents[0],
        "text",
        None,
    )

    if not isinstance(catalog_text, str):
        raise TypeError(
            "k8s://runbooks did not return text content"
        )

    try:
        catalog_data = json.loads(
            catalog_text
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "k8s://runbooks returned invalid JSON"
        ) from exc

    show_result(
        "k8s://runbooks",
        catalog_data,
    )


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Kubernetes MCP smoke client"
        )
    )

    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        required=True,
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8081/mcp",
    )

    parser.add_argument(
        "--namespace",
        default="default",
    )

    parser.add_argument(
        "--deployment",
    )

    args = parser.parse_args()

    if not args.namespace.strip():
        parser.error(
            "--namespace must not be empty"
        )

    if (
        args.deployment is not None
        and not args.deployment.strip()
    ):
        parser.error(
            "--deployment must not be empty"
        )

    return args


async def main() -> int:
    """Run the smoke client."""
    args = parse_args()

    if args.transport == "stdio":
        target: StdioServerParameters | str = (
            StdioServerParameters(
                command=sys.executable,
                args=[
                    str(
                        PROJECT_ROOT
                        / "server.py"
                    ),
                    "--transport",
                    "stdio",
                ],
                cwd=PROJECT_ROOT,
            )
        )
    else:
        target = args.url

    async with Client(
        target,
        mode="legacy",
    ) as client:
        try:
            await smoke(
                client,
                args.namespace,
                args.deployment,
            )
        except (
            RuntimeError,
            TypeError,
        ) as exc:
            print(
                f"Smoke failed: {exc}",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
