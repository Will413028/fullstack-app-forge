"""Versioned fixed template data; rendering never executes generated source on the host."""

import hashlib
import json
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TodoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="我的待辦清單", min_length=1, max_length=80)
    description: str = Field(default="將想法化為下一個行動。", max_length=500)
    theme: Literal["sage", "indigo", "amber"] = "sage"


def render_todo(spec: TodoSpec) -> dict[str, str]:
    assets = files("forge").joinpath("template_assets")
    outputs = {
        "backend/app.py": assets.joinpath("api.py.tpl").read_text(),
        "backend/pyproject.toml": assets.joinpath("pyproject.toml").read_text(),
        "backend/uv.lock": assets.joinpath("uv.lock").read_text(),
        "backend/requirements.txt": assets.joinpath("requirements.txt").read_text(),
        "frontend/app/page.tsx": assets.joinpath("page.tsx.tpl").read_text().replace(
            "__FORGE_SPEC_JSON__", json.dumps(spec.model_dump(), ensure_ascii=False)
        ),
        "frontend/app/layout.tsx": assets.joinpath("layout.tsx.tpl").read_text(),
        "frontend/app/globals.css": assets.joinpath("globals.css.tpl").read_text(),
        "frontend/app/api/[...path]/route.ts": assets.joinpath("route.ts.tpl").read_text(),
        "frontend/package.json": assets.joinpath("package.json").read_text(),
        "frontend/package-lock.json": assets.joinpath("package-lock.json").read_text(),
        "frontend/next.config.mjs": "export default {output: 'standalone'};\n",
        "README.md": "# Generated Todo application\n\nNext.js + FastAPI + PostgreSQL.\n",
        "forge-spec.json": json.dumps(spec.model_dump(), ensure_ascii=False, indent=2) + "\n",
    }
    return outputs


def source_manifest(source: dict[str, str]) -> dict:
    return {
        "template_version": "next-fastapi-todo-1",
        "files": [
            {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest(),
             "bytes": len(content.encode())}
            for path, content in sorted(source.items())
        ],
    }
