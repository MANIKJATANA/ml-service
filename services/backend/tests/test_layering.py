"""Layering acceptance test for the backend (decisions/0022).

``domain/`` and ``services/`` must not import any concrete IO library (SQLAlchemy,
asyncpg, redis, httpx, supabase, fastapi, pydantic, auth crypto), *nor* any internal
edge package (``adapters``/``api``/``wiring``/``workers``/``db``) — only the edge
layers may import those. This is the AST form of the ML service's grep, adapted to
the backend's libraries.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = {
    "sqlalchemy",
    "asyncpg",
    "redis",
    "httpx",
    "supabase",
    "storage3",
    "pydantic",
    "fastapi",
    "passlib",
    "jwt",
    "argon2",
}

# Internal edge packages a pure layer may never reach (decisions/0022).
FORBIDDEN_INTERNAL_PREFIXES = (
    "backend.adapters",
    "backend.api",
    "backend.wiring",
    "backend.workers",
    "backend.db",
)

SRC = Path(__file__).resolve().parent.parent / "src" / "backend"
PURE_LAYERS = ("domain", "services")


def _pure_layer_files() -> list[Path]:
    files: list[Path] = []
    for layer in PURE_LAYERS:
        files.extend((SRC / layer).rglob("*.py"))
    return files


def _package_of(path: Path) -> str:
    for layer in PURE_LAYERS:
        if path.is_relative_to(SRC / layer):
            rel = path.relative_to(SRC / layer).parent
            parts = ("backend", layer, *rel.parts)
            return ".".join(parts)
    raise AssertionError(f"{path} is not under a pure layer")


def _is_forbidden_internal(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in FORBIDDEN_INTERNAL_PREFIXES
    )


def _is_forbidden_absolute(module: str) -> bool:
    return module.split(".")[0] in FORBIDDEN or _is_forbidden_internal(module)


def _resolve_relative(module: str | None, level: int, package: str) -> str:
    base = package.rsplit(".", level - 1)[0]
    return f"{base}.{module}" if module else base


def _offending_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _package_of(path)
    offenders: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_absolute(alias.name):
                    offenders.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and _is_forbidden_absolute(node.module):
                    offenders.add(node.module)
            else:
                resolved = _resolve_relative(node.module, node.level, package)
                candidates = (
                    [resolved]
                    if node.module
                    else [f"{resolved}.{alias.name}" for alias in node.names]
                )
                offenders.update(c for c in candidates if _is_forbidden_internal(c))
    return offenders


def test_pure_layers_import_no_concrete_libs() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _pure_layer_files():
        bad = _offending_imports(path)
        if bad:
            offenders[str(path)] = bad
    assert not offenders, f"Forbidden imports in pure layers: {offenders}"


def test_scan_is_not_vacuous() -> None:
    assert len(_pure_layer_files()) >= 3
