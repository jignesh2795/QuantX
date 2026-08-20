"""Canonical identity and versioning for historical research datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    """Immutable identity for a normalized historical dataset."""

    dataset_id: str
    version: str
    source_id: str
    schema_version: str
    content_fingerprint: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (self.dataset_id, self.version, self.source_id, self.schema_version, self.content_fingerprint):
            if not name.strip():
                raise ValueError("dataset identity fields must not be empty")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "source_id": self.source_id,
            "schema_version": self.schema_version,
            "content_fingerprint": self.content_fingerprint,
            "metadata": dict(sorted(self.metadata.items())),
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def fingerprint_bytes(payload: bytes) -> str:
    """Return the SHA-256 fingerprint of the exact source payload bytes."""
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """Version registration tying a dataset name to exact source content."""

    identity: DatasetIdentity
    parent_version: str | None = None

    @property
    def version_key(self) -> str:
        return self.identity.fingerprint()
