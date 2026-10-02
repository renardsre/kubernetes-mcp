"""End-to-end MCP workflow validation."""

import argparse
import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def extract_runbook_uri(result: object) -> str:
    if not isinstance(result, dict):
        raise RuntimeError("search_runbooks returned unexpected result")

    items = result.get("result")

    if not isinstance(items, list) or not items:
        raise RuntimeError("No matching runbook found")

    first = items[0]

    if not isinstance(first, dict):
        raise RuntimeError("Invalid runbook search result")

    uri = first.get("uri")

    if not isinstance(uri, str) or not uri:
        raise RuntimeError("Runbook result has no URI")

    return uri


async def validate_oom_workflow(
    client: Client,
    namespace: str,
    deployment: str,
) -> None:
    print("=== L4 END-TO-END WORKFLOW ===")
    print(f"Target: {namespace}/{deployment}")

    # 1. Identify / classify
    inspection = await client.call_tool(
        "inspect_deployment_health",
        {
            "namespace": namespace,
            "name": deployment,
        },
    )

    if inspection.is_error:
        raise RuntimeError(
            f"inspect_deployment_health failed: {inspection.content}"
        )

    data = inspection.structured_content

    if not isinstance(data, dict):
        raise RuntimeError(
            "inspect_deployment_health returned no structured content"
        )

    failure_class = data.get("failure_class")
    evidence_sufficient = data.get("evidence_sufficient")
    logs_recommended = data.get("logs_recommended")
    recommended_log_targets = data.get("recommended_log_targets")

    print(f"Failure class: {failure_class}")
    print(f"Evidence sufficient: {evidence_sufficient}")
    print(f"Logs recommended: {logs_recommended}")

    if failure_class != "OOMKilled":
        raise RuntimeError(
            f"Expected OOMKilled, got {failure_class!r}"
        )

    # 2. Find matching runbook
    search = await client.call_tool(
        "search_runbooks",
        {
            "query": failure_class,
            "limit": 3,
        },
    )

    if search.is_error:
        raise RuntimeError(
            f"search_runbooks failed: {search.content}"
        )

    runbook_uri = extract_runbook_uri(
        search.structured_content
    )

    print(f"Runbook: {runbook_uri}")

    # 3. Read actual runbook body
    resource = await client.read_resource(
        runbook_uri
    )

    if not resource.contents:
        raise RuntimeError(
            f"{runbook_uri} returned no content"
        )

    runbook_text = getattr(
        resource.contents[0],
        "text",
        None,
    )

    if not isinstance(runbook_text, str):
        raise RuntimeError(
            f"{runbook_uri} did not return text content"
        )

    # 4. Validate runbook-driven decision
    if "OOMKilled" not in runbook_text:
        raise RuntimeError(
            "Selected runbook body does not describe OOMKilled"
        )

    if evidence_sufficient is not True:
        raise RuntimeError(
            "OOMKilled evidence should be sufficient"
        )

    if logs_recommended is not False:
        raise RuntimeError(
            "OOMKilled should not recommend logs"
        )

    if recommended_log_targets not in ([], None):
        raise RuntimeError(
            "OOMKilled should not provide log targets"
        )

    # Optional but useful:
    # prove that the runbook itself contains the no-log policy.
    if "Do not run tool `get_pod_logs`" not in runbook_text:
        raise RuntimeError(
            "OOMKilled runbook does not contain expected no-log policy"
        )

    print("Decision: no additional pod logs required")
    print("Stop condition: reached")
    print("Result: PASS")


async def validate_crashloop_workflow(
    client: Client,
    namespace: str,
    deployment: str,
) -> None:
    print("=== CRASHLOOP END-TO-END WORKFLOW ===")
    print(f"Target: {namespace}/{deployment}")

    inspection = await client.call_tool(
        "inspect_deployment_health",
        {"namespace": namespace, "name": deployment},
    )
    if inspection.is_error:
        raise RuntimeError(
            f"inspect_deployment_health failed: {inspection.content}"
        )

    data = inspection.structured_content
    if not isinstance(data, dict):
        raise RuntimeError(  # noqa: TRY004 - handled as a workflow failure below
            "inspect_deployment_health returned no structured content"
        )
    if data.get("failure_class") != "CrashLoopBackOff":
        raise RuntimeError(
            f"Expected CrashLoopBackOff, got {data.get('failure_class')!r}"
        )
    if data.get("logs_recommended") is not True:
        raise RuntimeError("CrashLoopBackOff should recommend logs")

    targets = data.get("recommended_log_targets")
    if not isinstance(targets, list) or len(targets) != 1:
        raise RuntimeError("Expected exactly one recommended log target")
    target = targets[0]
    if (
        not isinstance(target, dict)
        or not isinstance(target.get("pod"), str)
        or not target["pod"]
        or not isinstance(target.get("container"), str)
        or not target["container"]
        or not isinstance(target.get("previous"), bool)
    ):
        raise RuntimeError("Invalid recommended log target")

    search = await client.call_tool(
        "search_runbooks",
        {"query": "CrashLoopBackOff", "limit": 3},
    )
    if search.is_error:
        raise RuntimeError(f"search_runbooks failed: {search.content}")
    runbook_uri = extract_runbook_uri(search.structured_content)
    print(f"Runbook: {runbook_uri}")

    resource = await client.read_resource(runbook_uri)
    if not resource.contents:
        raise RuntimeError(f"{runbook_uri} returned no content")
    runbook_text = getattr(resource.contents[0], "text", None)
    if not isinstance(runbook_text, str) or "CrashLoopBackOff" not in runbook_text:
        raise RuntimeError("Selected runbook body does not describe CrashLoopBackOff")

    logs = await client.call_tool(
        "get_pod_logs",
        {
            "namespace": namespace,
            "name": target["pod"],
            "container": target["container"],
            "previous": target["previous"],
        },
    )
    if logs.is_error:
        raise RuntimeError(f"get_pod_logs failed: {logs.content}")

    print("Decision: fetched exactly one recommended log target")
    print("Result: PASS")


async def validate_failure_workflow(client: Client, namespace: str) -> bool:
    try:
        result = await client.call_tool(
            "inspect_deployment_health",
            {"namespace": namespace, "name": "does-not-exist"},
            read_timeout_seconds=5,
        )
        missing_deployment = result.is_error is True
    except (MCPError, TimeoutError, RuntimeError):
        missing_deployment = False
    print(f"{'PASS' if missing_deployment else 'FAIL'} inspect nonexistent Deployment")

    try:
        result = await client.call_tool(
            "find_unhealthy_deployments",
            {"namespace": "does-not-exist"},
            read_timeout_seconds=5,
        )
        missing_namespace = result.is_error is True
    except (MCPError, TimeoutError, RuntimeError):
        missing_namespace = False
    print(f"{'PASS' if missing_namespace else 'FAIL'} find nonexistent namespace")

    try:
        await client.read_resource("k8s://runbooks/does-not-exist")
        missing_runbook = False
    except MCPError as exc:
        missing_runbook = (
            exc.code == INVALID_PARAMS and "does-not-exist" in exc.message
        )
    except (TimeoutError, RuntimeError):
        missing_runbook = False
    print(f"{'PASS' if missing_runbook else 'FAIL'} read nonexistent runbook")

    try:
        await client.get_prompt("kubernetes_service_investigation", {})
        missing_arguments = False
    except MCPError as exc:
        missing_arguments = (
            "Missing required arguments" in exc.message
            and "namespace" in exc.message
            and "deployment" in exc.message
        )
    except (TimeoutError, RuntimeError):
        missing_arguments = False
    print(f"{'PASS' if missing_arguments else 'FAIL'} get prompt without required args")

    passed = all(
        (missing_deployment, missing_namespace, missing_runbook, missing_arguments)
    )
    print(f"Overall: {'PASS' if passed else 'FAIL'}")
    return passed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate end-to-end MCP workflow"
    )

    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        required=True,
    )

    parser.add_argument(
        "--scenario",
        choices=("oom", "crashloop", "failure"),
        default="oom",
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8081/mcp",
    )

    parser.add_argument(
        "--namespace",
        default="sandbox",
    )

    parser.add_argument(
        "--deployment",
        default="holmes-oom",
    )

    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    if args.transport == "stdio":
        target: StdioServerParameters | str = StdioServerParameters(
            command=sys.executable,
            args=[
                str(PROJECT_ROOT / "server.py"),
                "--transport",
                "stdio",
            ],
            cwd=PROJECT_ROOT,
        )
    else:
        target = args.url

    async with Client(
        target,
        mode="legacy",
        read_timeout_seconds=5 if args.scenario == "failure" else None,
    ) as client:
        try:
            if args.scenario == "failure":
                return 0 if await validate_failure_workflow(client, args.namespace) else 1
            workflow = (
                validate_crashloop_workflow
                if args.scenario == "crashloop"
                else validate_oom_workflow
            )
            await workflow(
                client,
                args.namespace,
                args.deployment,
            )
        except RuntimeError as exc:
            print(
                f"Result: FAIL — {exc}",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
