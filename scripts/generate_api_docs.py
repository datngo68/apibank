"""Generate docs/api.md from FastAPI OpenAPI schema."""

from __future__ import annotations

import json
from pathlib import Path

from apps.api.main import create_app


def render_markdown(spec: dict) -> str:  # type: ignore[type-arg]
    lines: list[str] = ["# APIBank HTTP API", ""]
    info = spec.get("info", {})
    lines.append(f"Version: {info.get('version', '0.1.0')}")
    lines.append("")
    lines.append("All requests use `Authorization: Bearer <api_key>` unless noted.")
    lines.append("")
    paths = spec.get("paths", {})
    for path in sorted(paths):
        for method, op in paths[path].items():
            summary = op.get("summary") or op.get("operationId") or ""
            tags = ", ".join(op.get("tags", []))
            lines.append(f"## {method.upper()} {path}")
            lines.append("")
            if tags:
                lines.append(f"Tags: {tags}")
            if summary:
                lines.append(f"Summary: {summary}")
            params = op.get("parameters", [])
            if params:
                lines.append("")
                lines.append("Parameters:")
                for param in params:
                    schema = param.get("schema", {})
                    lines.append(
                        f"- `{param.get('name')}` ({param.get('in')}) – {schema.get('type', '?')}"
                    )
            request_body = op.get("requestBody")
            if request_body:
                lines.append("")
                lines.append("Body: see schema in OpenAPI JSON.")
            responses = op.get("responses", {})
            if responses:
                lines.append("")
                lines.append("Responses:")
                for status_code, response in responses.items():
                    desc = response.get("description", "")
                    lines.append(f"- `{status_code}` {desc}")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    app = create_app()
    spec = app.openapi()
    out_dir = Path("docs")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "api.md").write_text(render_markdown(spec), encoding="utf-8")
    (out_dir / "openapi.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'api.md'}")


if __name__ == "__main__":
    main()
