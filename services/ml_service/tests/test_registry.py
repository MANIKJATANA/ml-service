"""wiring.registry: name resolution + error handling.

Only CPU-safe adapters are actually imported here (local_fs, inproc, faiss,
opencv, postgres); the Linux-only insightface/decord targets are asserted
structurally (their dotted strings) without importing them, so this stays green
on Windows/CI.
"""

from __future__ import annotations

import pytest
from ml_service.domain.errors import ConfigurationError
from ml_service.wiring import registry

ALL_REGISTRIES = [
    registry.DETECTOR_REGISTRY,
    registry.EMBEDDER_REGISTRY,
    registry.VECTOR_INDEX_REGISTRY,
    registry.INDEX_STORE_REGISTRY,
    registry.MEDIA_STORE_REGISTRY,
    registry.VIDEO_EXTRACTOR_REGISTRY,
    registry.MATCH_REPO_REGISTRY,
    registry.DETECTION_REPO_REGISTRY,
    registry.THRESHOLD_PROVIDER_REGISTRY,
    registry.REFERENCE_PHOTO_REPO_REGISTRY,
    registry.BACKEND_EVENT_STORE_REGISTRY,
    registry.QUEUE_REGISTRY,
]


def test_every_target_is_module_colon_class() -> None:
    for reg in ALL_REGISTRIES:
        assert reg  # non-empty
        for name, target in reg.items():
            module_path, sep, class_name = target.partition(":")
            assert sep == ":", f"{name} -> {target} missing module:Class"
            assert module_path.startswith("ml_service.adapters")
            assert class_name


@pytest.mark.parametrize(
    ("reg", "name"),
    [
        (registry.MEDIA_STORE_REGISTRY, "local_fs"),
        (registry.INDEX_STORE_REGISTRY, "local_fs"),
        (registry.VECTOR_INDEX_REGISTRY, "faiss"),
        (registry.VIDEO_EXTRACTOR_REGISTRY, "opencv"),
        (registry.MATCH_REPO_REGISTRY, "postgres"),
        (registry.DETECTION_REPO_REGISTRY, "postgres"),
        (registry.THRESHOLD_PROVIDER_REGISTRY, "postgres"),
        (registry.REFERENCE_PHOTO_REPO_REGISTRY, "postgres"),
        (registry.BACKEND_EVENT_STORE_REGISTRY, "postgres"),
        (registry.QUEUE_REGISTRY, "inproc"),
    ],
)
def test_resolve_imports_cpu_safe_classes(reg: dict[str, str], name: str) -> None:
    cls = registry.resolve(reg, name)
    assert isinstance(cls, type)


def test_resolve_unknown_name_raises() -> None:
    with pytest.raises(ConfigurationError, match="unknown adapter impl"):
        registry.resolve(registry.QUEUE_REGISTRY, "kafka")


def test_resolve_bad_target_raises() -> None:
    with pytest.raises(ConfigurationError, match="cannot import"):
        registry.resolve({"x": "ml_service.adapters.nope:Nope"}, "x")
