"""Vendor-neutral dataset registration and catalog boundary.

A dataset name/version must never silently refer to different source
content: registering an exact duplicate is an idempotent no-op, while the
same declared identity with different content is an explicit conflict.

This slice is metadata registration only. It does not fetch market data,
verify artifacts, store observations, or claim that a content fingerprint
has been independently verified.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import quote as url_quote

from .dataset import DatasetIdentity, DatasetVersion


@runtime_checkable
class DatasetCatalog(Protocol):
    """Durable registration boundary for declared dataset versions."""

    def register(self, dataset_version: DatasetVersion) -> DatasetVersion:
        """Register a version; exact duplicates return the stored equivalent."""
        ...

    def get(self, dataset_id: str, version: str) -> DatasetVersion | None:
        """Return the registered version, or None when never registered."""
        ...


class InMemoryDatasetCatalog:
    """Deterministic catalog for unit tests and development use."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], DatasetVersion] = {}

    def register(self, dataset_version: DatasetVersion) -> DatasetVersion:
        key = _identity_key(dataset_version.identity.dataset_id, dataset_version.identity.version)
        stored = self._versions.get(key)
        if stored is None:
            self._versions[key] = dataset_version
            return dataset_version
        if stored != dataset_version:
            raise ValueError(
                "dataset version already registered with different identity: "
                f"{dataset_version.identity.dataset_id} "
                f"{dataset_version.identity.version}"
            )
        return stored

    def get(self, dataset_id: str, version: str) -> DatasetVersion | None:
        return self._versions.get(_identity_key(dataset_id, version))


class FilesystemDatasetCatalog:
    """Local JSON metadata persistence for dataset registrations.

    Registrations live under ``<root>/datasets/`` at deterministic
    percent-encoded paths derived from the declared dataset identity, so a
    dataset is always resolved by ``(dataset_id, version)`` rather than by
    content fingerprint. Writes are atomic via temporary-file replace and
    never partially overwrite an existing registration.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._datasets_dir = self._root / "datasets"
        self._datasets_dir.mkdir(parents=True, exist_ok=True)

    def register(self, dataset_version: DatasetVersion) -> DatasetVersion:
        path = self._path_for(dataset_version.identity.dataset_id, dataset_version.identity.version)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stored = self._read_version(path)
            if stored != dataset_version:
                raise ValueError(
                    "dataset version already registered with different identity: "
                    f"{dataset_version.identity.dataset_id} "
                    f"{dataset_version.identity.version}"
                )
            return stored
        _atomic_write(path, _version_payload(dataset_version))
        return dataset_version

    def get(self, dataset_id: str, version: str) -> DatasetVersion | None:
        path = self._path_for(dataset_id, version)
        if not path.exists():
            return None
        return self._read_version(path)

    def _path_for(self, dataset_id: str, version: str) -> Path:
        if not dataset_id.strip():
            raise ValueError("dataset_id must not be empty")
        if not version.strip():
            raise ValueError("version must not be empty")
        return self._datasets_dir / _safe_segment(dataset_id) / f"{_safe_segment(version)}.json"

    @staticmethod
    def _read_version(path: Path) -> DatasetVersion:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"malformed dataset registration: {path.name}") from exc
        return _version_from_payload(payload, path.name)


def _identity_key(dataset_id: str, version: str) -> tuple[str, str]:
    return (dataset_id, version)


def _safe_segment(value: str) -> str:
    """Encode one path segment deterministically and reversibly."""
    return url_quote(value, safe="")


def _version_payload(dataset_version: DatasetVersion) -> dict[str, object]:
    identity = dataset_version.identity
    return {
        "dataset_id": identity.dataset_id,
        "version": identity.version,
        "source_id": identity.source_id,
        "schema_version": identity.schema_version,
        "content_fingerprint": identity.content_fingerprint,
        "metadata": dict(sorted(identity.metadata.items())),
        "parent_version": dataset_version.parent_version,
    }


def _version_from_payload(payload: object, name: str) -> DatasetVersion:
    if not isinstance(payload, dict):
        raise ValueError(f"malformed dataset registration: {name}")
    try:
        metadata = payload["metadata"]
        if not isinstance(metadata, Mapping):
            raise ValueError("dataset metadata must be a mapping")
        parent_version = payload.get("parent_version")
        if parent_version is not None and not isinstance(parent_version, str):
            raise ValueError("dataset parent_version must be a string or null")
        identity = DatasetIdentity(
            dataset_id=payload["dataset_id"],
            version=payload["version"],
            source_id=payload["source_id"],
            schema_version=payload["schema_version"],
            content_fingerprint=payload["content_fingerprint"],
            metadata=dict(metadata),
        )
        return DatasetVersion(
            identity=identity,
            parent_version=parent_version,
        )
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError(f"malformed dataset registration: {name}") from exc


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


__all__ = [
    "DatasetCatalog",
    "FilesystemDatasetCatalog",
    "InMemoryDatasetCatalog",
]
