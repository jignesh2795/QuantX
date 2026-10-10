"""Bind a successful dataset ingestion result to the research-run identity.

The composer derives ``dataset_id`` and ``dataset_version`` exclusively from
the registered identity carried by the ingestion result and requires every
other research-run field to be caller-declared. It creates no provenance,
fingerprint, repository, or lifecycle objects of its own: the existing
``ResearchRunSpec.to_provenance()`` remains the sole reproducibility path.
"""

from __future__ import annotations

from quantx.application.dataset_ingestion import HistoricalDatasetIngestionResult
from quantx.research.provenance import ResearchRunConfiguration
from quantx.research.result import ResearchRunSpec


def research_run_spec_from_ingestion(
    result: HistoricalDatasetIngestionResult,
    *,
    run_id: str,
    instrument_master_version: str,
    market_rule_version: str,
    execution_model_version: str,
    simulation_profile: str,
    code_revision: str,
    configuration_revision: str,
    random_seed: int | None = None,
    run_configuration: ResearchRunConfiguration | None = None,
) -> ResearchRunSpec:
    """Build the canonical research-run declaration for one ingested dataset version.

    The dataset identity comes from the registered ``DatasetVersion`` carried
    by the result. The convenience fields on the result must agree with that
    registered identity; any mismatch fails closed. All other research-run
    fields must be caller-declared; nothing is inferred from the environment,
    and ingestion quality evidence stays on the result untouched.
    """
    identity = result.dataset_version.identity
    if (
        result.dataset_id != identity.dataset_id
        or result.version != identity.version
        or result.source_id != identity.source_id
    ):
        raise ValueError(
            "ingestion result identity fields do not match registered dataset identity"
        )
    for name, value in (
        ("run_id", run_id),
        ("instrument_master_version", instrument_master_version),
        ("market_rule_version", market_rule_version),
        ("execution_model_version", execution_model_version),
        ("simulation_profile", simulation_profile),
        ("code_revision", code_revision),
        ("configuration_revision", configuration_revision),
    ):
        if not value.strip():
            raise ValueError(f"{name} must not be empty")
    return ResearchRunSpec(
        run_id=run_id,
        dataset_id=identity.dataset_id,
        dataset_version=identity.version,
        instrument_master_version=instrument_master_version,
        market_rule_version=market_rule_version,
        execution_model_version=execution_model_version,
        simulation_profile=simulation_profile,
        code_revision=code_revision,
        configuration_revision=configuration_revision,
        random_seed=random_seed,
        run_configuration=run_configuration,
    )


__all__ = ["research_run_spec_from_ingestion"]
