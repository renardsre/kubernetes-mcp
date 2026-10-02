import asyncio
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError
from urllib.request import urlopen

import httpx2
from mcp import Client, StdioServerParameters
from mcp_types import ResourceTemplateReference

import server
from client import capability_surface
from mcp_server import create_mcp_server

PROJECT_ROOT = Path(__file__).parents[1]


class TransportTests(unittest.TestCase):
    def test_entrypoint_selects_transport_without_registering_capabilities(self) -> None:
        for transport, expected in (
            ("stdio", {"transport": "stdio"}),
            (
                "streamable-http",
                {"transport": "streamable-http", "host": "127.0.0.1", "port": 8081},
            ),
        ):
            with self.subTest(transport=transport):
                mcp = Mock()
                with patch("server.create_mcp_server", return_value=mcp), patch.object(
                    sys, "argv", ["server.py", "--transport", transport]
                ):
                    server.main()
                mcp.run.assert_called_once_with(**expected)

    def test_shared_factory_has_one_capability_surface(self) -> None:
        async def discover() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
            async with Client(create_mcp_server(), mode="legacy") as first:
                first_surface = await capability_surface(first)
            async with Client(create_mcp_server(), mode="legacy") as second:
                second_surface = await capability_surface(second)
            return first_surface, second_surface

        first, second = asyncio.run(discover())
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            {
                "tools": [
                    "find_unhealthy_deployments",
                    "get_pod_logs",
                    "inspect_deployment_health",
                    "search_runbooks",
                ],
                "prompts": ["kubernetes_service_investigation", "namespace_health_review"],
                "resources": ["k8s://runbooks"],
                "resource_templates": ["k8s://runbooks/{slug}"],
            },
        )

    def test_health_route_is_preserved(self) -> None:
        async def request() -> tuple[tuple[int, object], tuple[int, object]]:
            app = create_mcp_server().streamable_http_app()
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client:
                health = await client.get("/health")
                root = await client.get("/")
                return (
                    (health.status_code, health.json()),
                    (root.status_code, root.json()),
                )

        self.assertEqual(
            asyncio.run(request()),
            (
                (
                    200,
                    {
                        "status_code": 200,
                        "health": "ok",
                        "service": "kubernetes-mcp",
                        "path": "/health",
                    },
                ),
                (200, {"status": "ok", "service": "kubernetes-mcp", "path": "/"}),
            ),
        )

    @unittest.skipUnless(
        os.environ.get("MCP_LIVE_TRANSPORT_TEST") == "1",
        "set MCP_LIVE_TRANSPORT_TEST=1 for live stdio/HTTP parity",
    )
    def test_live_stdio_and_http_capability_parity(self) -> None:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]

        process = subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "server.py"),
                "--transport",
                "streamable-http",
                "--port",
                str(port),
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            health_url = f"http://127.0.0.1:{port}/health"
            for _ in range(50):
                if process.poll() is not None:
                    error_output = (
                        process.stderr.read() if process.stderr is not None else b""
                    )
                    raise RuntimeError(f"HTTP server exited: {error_output!r}")
                try:
                    with urlopen(health_url, timeout=0.2) as response:
                        self.assertEqual(response.status, 200)
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                self.fail("HTTP server did not become healthy within 5 seconds")

            async def compare() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
                async def probe(client: Client) -> dict[str, list[str]]:
                    surface = await capability_surface(client)
                    resource = await client.read_resource("k8s://runbooks/imagepullbackoff")
                    self.assertIn("# ImagePullBackOff", str(resource.contents[0]))
                    completion = await client.complete(
                        ResourceTemplateReference(uri="k8s://runbooks/{slug}"),
                        {"name": "slug", "value": "o"},
                    )
                    self.assertEqual(completion.completion.values, ["oomkilled"])
                    return surface

                stdio = StdioServerParameters(
                    command=sys.executable,
                    args=[str(PROJECT_ROOT / "server.py"), "--transport", "stdio"],
                    cwd=PROJECT_ROOT,
                )
                async with Client(stdio, mode="legacy", read_timeout_seconds=10) as client:
                    stdio_surface = await probe(client)
                async with Client(
                    f"http://127.0.0.1:{port}/mcp",
                    mode="legacy",
                    read_timeout_seconds=10,
                ) as client:
                    http_surface = await probe(client)
                return stdio_surface, http_surface

            stdio_surface, http_surface = asyncio.run(compare())
            self.assertEqual(stdio_surface, http_surface)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr is not None:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
