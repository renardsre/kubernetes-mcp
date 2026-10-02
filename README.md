# Kubernetes MCP server

A read-only MCP server for investigating Kubernetes Deployments. It exposes four focused Tools, two Prompts, and a set of troubleshooting runbooks. The same capabilities work over stdio and Streamable HTTP.

The main workflow is simple: inspect a Deployment once, use the evidence it returns, and collect more only when there is a specific unanswered question.

## Architecture

```text
server.py                    # CLI and transport startup
mcp_server.py                # one MCPServer factory for both transports
client.py                    # read-only smoke client for either transport
tools/kubernetes.py          # four Tool schemas and thin MCP wrappers
services/kubernetes.py       # Kubernetes API reads, evidence correlation, classification
prompts/
  common.py                  # shared Jinja renderer and validators
  kubernetes.py              # explicit Prompt registration
  templates/                 # Markdown/Jinja Prompt bodies
resources/
  catalog.py                 # deterministic runbook metadata, search, loading, completion
  kubernetes.py              # catalog Resource, runbook template, completion registration
  runbooks/                  # Markdown runbooks
tests/                       # unit, schema, and transport checks
```

`mcp_server.py` registers capabilities once. `server.py` only chooses the transport. Kubernetes API calls and evidence processing live in `services/kubernetes.py`, separate from MCP Tool registration.

The four Tools are:

- `inspect_deployment_health` gathers bounded health evidence for a known Deployment. It combines Deployment, ReplicaSet, Pod, container, event, and scheduling data using the existing four Kubernetes reads.
- `find_unhealthy_deployments` finds unhealthy Deployment candidates in one namespace.
- `get_pod_logs` reads bounded logs from a targeted Pod and container.
- `search_runbooks` finds relevant runbooks by failure class or symptom. It returns metadata and a Resource URI, not the runbook body.

The inspection result includes routing fields such as `evidence_sufficient`, `logs_recommended`, and `previous_logs_recommended`. It also separates three levels of failure information:

- `primary_failure_reason` is a selected low-level Kubernetes reason.
- `failure_class` is the normalized operational class. It is `null` when the server cannot classify the failure.
- `failure_signal` is a more specific mechanism when one is available.

For example, `primary_failure_reason=Error` can coexist with `failure_class=CrashLoopBackOff` and `failure_signal=FailedPostStartHook`. The raw reason is supporting evidence, not a competing diagnosis. An exit code alone does not prove a specific mechanism.

The Prompts are `kubernetes_service_investigation` and `namespace_health_review`. Runbook Resources are `k8s://runbooks` for the catalog and `k8s://runbooks/{slug}` for the Markdown content. Slug completion is available. Search ranking is deterministic, not an AI confidence score.

Tools query evidence. Prompts frame tasks. Resources provide operational guidance. Skills and Agent policies coordinate the investigation. No Tool in this server changes the cluster.

## Run the server

This project runs as a script, so `[tool.uv] package = false` is intentional. You need a working kubeconfig for Kubernetes calls.

```bash
uv sync

# Choose one transport
uv run python server.py --transport stdio
uv run python server.py --transport streamable-http
```

HTTP listens on `127.0.0.1:8081` by default. The MCP endpoint is `/mcp`, and the health endpoint is `/health`. Use `--host` and `--port` to change the binding. In stdio mode, keep stdout free of application prints. Both transports use `server.py`, not the old `server-http.py` or `server-stdio.py` entrypoints.

## Read-only smoke client

```bash
uv run python client.py --transport stdio
uv run python client.py --transport http --url http://127.0.0.1:8081/mcp

# Inspect a specific workload instead of namespace-wide discovery:
uv run python client.py --transport stdio \
  --namespace sandbox --deployment service-crashloop
```

The smoke client lists all MCP capabilities, calls one read-only workload Tool, searches for a runbook, reads its Markdown body, retrieves a Prompt, and reads the runbook catalog.

Without `--deployment`, it checks namespace `default` using `find_unhealthy_deployments`. You can set another namespace with `--namespace`. With `--deployment`, it inspects exactly that Deployment and fails clearly if it does not exist. HTTP mode needs a running server. Stdio mode starts its own server process.

## MCP Inspector (HTTP)

Start the HTTP server first, then use Inspector CLI to explore its capabilities:

```bash
npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8081/mcp --transport http --method tools/list

npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8081/mcp --transport http --method prompts/list

npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8081/mcp --transport http --method prompts/get \
  --prompt-name kubernetes_service_investigation \
  --prompt-args namespace=sandbox --prompt-args deployment=service-crashloop \
  --prompt-args use_runbook=false

npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8081/mcp --transport http --method resources/list

npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8081/mcp --transport http --method resources/templates/list

npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8081/mcp --transport http --method resources/read \
  --uri 'k8s://runbooks/imagepullbackoff'
```

## Development

```bash
make sync          # install dependencies
make run           # start the HTTP server
make run-stdio     # start the stdio server
make dev           # start HTTP with auto-reload
make smoke-stdio   # run the read-only stdio smoke client
make smoke-http    # run the read-only HTTP smoke client
make test          # run unit tests
make lint          # run Ruff
make typecheck     # run Basedpyright
make check         # run lint, typecheck, and tests
make clean         # remove generated caches
```

`make run` starts the HTTP server through the `run-http` target. `make dev` uses `watchfiles` to restart it after source or template changes. `make clean` keeps `.venv` and `uv.lock`.

To check live stdio/HTTP parity when local socket binding is available, run:

```bash
MCP_LIVE_TRANSPORT_TEST=1 uv run python -m unittest discover -s tests -p test_transport.py -v
```

## Adding a Tool

Check the four existing Tools first. Add a new one only when it provides a genuinely new, bounded capability. Do not add a low-level Pod or Event Tool when `inspect_deployment_health` already supplies the evidence.

Put Kubernetes reads and correlation in `services/kubernetes.py`. Put the typed `@mcp.tool()` wrapper in `tools/kubernetes.py`. Keep its output bounded and its description short. Test registration, input bounds, success and error cases, and the number of Kubernetes API reads. A write Tool needs a separate safety and approval design.

## Adding a Prompt

Create `prompts/templates/<name>.md` for the wording. Then register an `@mcp.prompt()` function in `prompts/kubernetes.py`, or in another domain module registered by `mcp_server.py`. The Python function defines the name, arguments, defaults, and validation. A Markdown file alone does not create a Prompt.

Reuse `render_prompt()` and `parse_bool()` from `prompts/common.py`. The Jinja environment uses `StrictUndefined`, `autoescape=False`, `trim_blocks=True`, and `lstrip_blocks=True`. Test `prompts/list`, required and optional arguments, rendered text, invalid values, and duplicate registration.

## Adding a Runbook

Add `resources/runbooks/<stable-lowercase-slug>.md` and register its metadata in `resources/catalog.py`. The catalog Resource, template, completion, and search use that metadata automatically.

Choose keywords that match real symptoms. Broad words can produce false positives. The `00-` prefix puts `00-service-triage` near the top of the alphabetical catalog, but gives it no special search rank. Test loading, unknown slugs, ranking, Resource reads, and completion. Runbooks should guide decisions without forcing repeated Kubernetes reads.

Unit tests cover behavior. Transport parity tests compare capability registrations. A live smoke test or Inspector session checks connectivity.
