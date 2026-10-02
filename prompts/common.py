from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)
# Jinja's built-in "namespace" global would mask a missing Prompt variable.
_TEMPLATE_ENV.globals.pop("namespace", None)


def render_prompt(template_name: str, **context: object) -> str:
    template = _TEMPLATE_ENV.get_template(template_name)
    return template.render(**context).removesuffix("\n")


def parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise MCPError(
            code=INVALID_PARAMS,
            message=f"{name} must be 'true' or 'false'",
        )
    return normalized == "true"
