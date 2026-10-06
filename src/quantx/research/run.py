"""Durable identity and lifecycle records for research execution instances."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from .artifacts import ResearchArtifactManifest
from .provenance import ResearchProvenance
from .result import ResearchResult


class ResearchRunState(StrEnum):
    """Lifecycle state of one persisted research execution instance."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ResearchRunRecord:
    """Immutable snapshot of one research execution instance."""

    run_id: str
    provenance: ResearchProvenance
    state: ResearchRunState = ResearchRunState.CREATED
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    result_id: UUID | None = None
    artifact_manifest_fingerprints: tuple[str, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.created_at.strip():
            raise ValueError("created_at must not be empty")

        for name in ("started_at", "completed_at"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be empty when provided")

        if self.state is ResearchRunState.CREATED:
            if self.started_at is not None:
                raise ValueError("CREATED research runs cannot have started_at")
            if self.completed_at is not None:
                raise ValueError("CREATED research runs cannot have completed_at")
            if self.result_id is not None:
                raise ValueError("CREATED research runs cannot have result_id")
            if self.failure_reason is not None:
                raise ValueError("CREATED research runs cannot have failure_reason")

        if self.state is ResearchRunState.RUNNING:
            if self.started_at is None:
                raise ValueError("RUNNING research runs require started_at")
            if self.completed_at is not None:
                raise ValueError("RUNNING research runs cannot have completed_at")
            if self.result_id is not None:
                raise ValueError("RUNNING research runs cannot have result_id")
            if self.failure_reason is not None:
                raise ValueError("RUNNING research runs cannot have failure_reason")

        if self.state is ResearchRunState.COMPLETED:
            if self.started_at is None:
                raise ValueError("COMPLETED research runs require started_at")
            if self.completed_at is None:
                raise ValueError("COMPLETED research runs require completed_at")
            if self.result_id is None:
                raise ValueError("COMPLETED research runs require result_id")
            if self.failure_reason is not None:
                raise ValueError("COMPLETED research runs cannot have failure_reason")

        if self.state is ResearchRunState.FAILED:
            if self.failure_reason is None or not self.failure_reason.strip():
                raise ValueError("FAILED research runs require failure_reason")
            if self.completed_at is not None:
                raise ValueError("FAILED research runs cannot have completed_at")
            if self.result_id is not None:
                raise ValueError("FAILED research runs cannot have result_id")

        if self.failure_reason is not None and not self.failure_reason.strip():
            raise ValueError("failure_reason must not be empty when provided")

        fingerprints = self.artifact_manifest_fingerprints
        if any(not item.strip() for item in fingerprints):
            raise ValueError("artifact manifest fingerprints must not be empty")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("artifact manifest fingerprints must be unique")

    @property
    def provenance_fingerprint(self) -> str:
        """Return the sole reproducibility identity for this run."""
        return self.provenance.fingerprint()

    def started(self, started_at: str) -> ResearchRunRecord:
        """Return the RUNNING snapshot for this run."""
        if not started_at.strip():
            raise ValueError("started_at must not be empty")
        if self.state is not ResearchRunState.CREATED:
            raise ValueError(f"cannot start research run from {self.state}")
        return replace(self, state=ResearchRunState.RUNNING, started_at=started_at)

    def completed(self, result: ResearchResult, completed_at: str) -> ResearchRunRecord:
        """Return the COMPLETED snapshot after binding a compatible result."""
        if self.state is not ResearchRunState.RUNNING:
            raise ValueError(f"cannot complete research run from {self.state}")
        if not completed_at.strip():
            raise ValueError("completed_at must not be empty")
        if result.spec.run_id != self.run_id:
            raise ValueError(
                "research result run_id does not match research run"
            )
        if result.fingerprint != self.provenance_fingerprint:
            raise ValueError("research result provenance fingerprint does not match research run")
        return replace(
            self,
            state=ResearchRunState.COMPLETED,
            completed_at=completed_at,
            result_id=result.result_id,
        )

    def failed(self, reason: str) -> ResearchRunRecord:
        """Return the terminal FAILED snapshot for this run."""
        if self.state not in {ResearchRunState.CREATED, ResearchRunState.RUNNING}:
            raise ValueError(f"cannot fail research run from {self.state}")
        if not reason.strip():
            raise ValueError("failure reason must not be empty")
        return replace(self, state=ResearchRunState.FAILED, failure_reason=reason)

    def with_manifest(self, manifest: ResearchArtifactManifest) -> ResearchRunRecord:
        """Return a snapshot with one provenance-compatible artifact manifest."""
        if self.state is ResearchRunState.FAILED:
            raise ValueError("cannot attach manifest to FAILED research run")
        if manifest.run_fingerprint != self.provenance_fingerprint:
            raise ValueError(
                "research artifact manifest run fingerprint does not match research run"
            )
        manifest_id = manifest.fingerprint()
        if manifest_id in self.artifact_manifest_fingerprints:
            raise ValueError("research artifact manifest already attached")
        return replace(
            self,
            artifact_manifest_fingerprints=(
                *self.artifact_manifest_fingerprints,
                manifest_id,
            ),
        )
