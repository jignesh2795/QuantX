from quantx.research.provenance import ResearchProvenance


def _provenance(**overrides):
    values = {
        "dataset_id": "nse-1m",
        "dataset_version": "2026-08-20",
        "instrument_master_version": "nse-contracts-v3",
        "market_rule_version": "india-rules-v2",
        "execution_model_version": "paper-core-v0.1",
        "simulation_profile": "REALISTIC",
        "code_revision": "abc123",
        "configuration_revision": "cfg456",
        "random_seed": 42,
        "extra": {"timezone": "Asia/Kolkata", "source": "exchange"},
    }
    values.update(overrides)
    return ResearchProvenance(**values)


def test_same_provenance_has_same_fingerprint() -> None:
    assert _provenance().fingerprint() == _provenance().fingerprint()


def test_fingerprint_changes_when_material_input_changes() -> None:
    assert _provenance().fingerprint() != _provenance(dataset_version="2026-08-21").fingerprint()


def test_extra_mapping_order_does_not_change_fingerprint() -> None:
    left = _provenance(extra={"a": "1", "b": "2"})
    right = _provenance(extra={"b": "2", "a": "1"})
    assert left.fingerprint() == right.fingerprint()
