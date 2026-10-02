.PHONY: sync run run-http run-stdio dev smoke-stdio smoke-http test lint typecheck check clean

sync:
	uv sync

run: run-http

run-http:
	uv run python server.py --transport streamable-http

run-stdio:
	uv run python server.py --transport stdio

dev:
	uv run watchfiles "python server.py --transport streamable-http" .

smoke-stdio:
	uv run python client.py --transport stdio

smoke-http:
	uv run python client.py --transport http

test:
	uv run python -m unittest discover -s tests -v

lint:
	uv run ruff check server.py mcp_server.py client.py tools services prompts resources tests

typecheck:
	uv run basedpyright server.py mcp_server.py client.py tools services prompts resources tests

check: lint typecheck test

clean:
	find tools services prompts resources tests -type d -name __pycache__ -prune -exec rm -r -- {} +
	rm -rf -- __pycache__ .pytest_cache .ruff_cache .pyright
