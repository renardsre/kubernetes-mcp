from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from prompts.kubernetes import register_kubernetes_prompts
from resources.kubernetes import register_kubernetes_resources
from tools.kubernetes import register_kubernetes_tools


def create_mcp_server() -> MCPServer:
    mcp = MCPServer("Kubernetes Operations MCP")
    register_kubernetes_tools(mcp)
    register_kubernetes_prompts(mcp)
    register_kubernetes_resources(mcp)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({
            "status_code": 200,
            "health": "ok",
            "service": "kubernetes-mcp",
            "path": "/health",
        })

    @mcp.custom_route("/", methods=["GET"])
    async def root(request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "kubernetes-mcp",
            "path": "/",
        })

    return mcp
