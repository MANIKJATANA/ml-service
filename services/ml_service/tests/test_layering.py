"""Layering acceptance test (architecture §5).

``domain/`` and ``orchestration/`` must not import any concrete ML/IO library,
*nor* any internal edge package (``adapters``/``api``/``workers``/``wiring``) —
only ``api``/``workers``/``wiring`` may import adapters. This is the AST form of
the doc's grep, extended to also catch absolute and relative imports of those
internal packages, not just third-party libs.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = {
    "faiss",
    "cv2",
    "insightface",
    "boto3",
    "azure",
    "sqlalchemy",
    "asyncpg",
    "redis",
    "decord",
    "numpy",
    "supabase",
    "storage3",
    "pydantic",
    "onnxruntime",
    "av",
    "PIL",
    "fastapi",
}

# Internal edge packages a pure layer may never reach (architecture §5).
FORBIDDEN_INTERNAL_PREFIXES = (
    "ml_service.adapters",
    "ml_service.api",
    "ml_service.workers",
    "ml_service.wiring",
)

SRC = Path(__file__).resolve().parent.parent / "src" / "ml_service"
PURE_LAYERS = ("domain", "orchestration")


def _pure_layer_files() -> list[Path]:
    files: list[Path] = []
    for layer in PURE_LAYERS:
        files.extend((SRC / layer).rglob("*.py"))
    return files


def _package_of(path: Path) -> str:
    """Package a pure-layer file resolves relative imports against.

    ``domain/`` and ``orchestration/`` are flat (architecture §5), so this is
    ``ml_service.domain`` or ``ml_service.orchestration``.
    """
    for layer in PURE_LAYERS:
        if path.is_relative_to(SRC / layer):
            return f"ml_service.{layer}"
    raise AssertionError(f"{path} is not under a pure layer")


def _is_forbidden_internal(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in FORBIDDEN_INTERNAL_PREFIXES
    )


def _is_forbidden_absolute(module: str) -> bool:
    """A third-party lib in FORBIDDEN, or an internal edge package."""
    return module.split(".")[0] in FORBIDDEN or _is_forbidden_internal(module)


def _resolve_relative(module: str | None, level: int, package: str) -> str:
    """Resolve a relative import target to an absolute module (importlib semantics)."""
    base = package.rsplit(".", level - 1)[0]
    return f"{base}.{module}" if module else base


def _offending_imports(path: Path) -> set[str]:
    """Imports in *path* that violate the pure-layer rule."""
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
                # ``from . import X`` resolves only to the package; fold in names.
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
    assert len(_pure_layer_files()) >= 8
