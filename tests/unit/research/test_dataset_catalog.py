"""Tests for the vendor-neutral dataset catalog boundary."""

import pytest

from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_catalog import (
    DatasetCatalog,
    FilesystemDatasetCatalog,
    InMemoryDatasetCatalog,
)


def _identity(**overrides) -> DatasetIdentity:
    values = {
        "dataset_id": "nse-equities",
        "version": "v1",
        "source_id": "dhan",
        "schema_version": "1",
        "content_fingerprint": fingerprint_bytes(b"ohlcv-bytes-v1"),
        "metadata": {"market": "NSE"},
    }
    values.update(overrides)
    return DatasetIdentity(**values)


def _version(**overrides) -> DatasetVersion:
    parent_version = overrides.pop("parent_version", None)
    return DatasetVersion(identity=_identity(**overrides), parent_version=parent_version)


def _catalogs(tmp_path):
    return (
        InMemoryDatasetCatalog(),
        FilesystemDatasetCatalog(tmp_path / "catalog"),
    )


def test_catalog_protocol_conformance(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        assert isinstance(catalog, DatasetCatalog)


def test_in_memory_registration_and_retrieval() -> None:
    catalog = InMemoryDatasetCatalog()
    version = _version()

    assert catalog.register(version) == version
    assert catalog.get("nse-equities", "v1") == version


def test_filesystem_registration_and_retrieval(tmp_path) -> None:
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    version = _version()

    assert catalog.register(version) == version
    assert catalog.get("nse-equities", "v1") == version


def test_exact_round_trip_equality(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        version = _version(parent_version="v0", metadata={"b": "2", "a": "1"})
        assert catalog.register(version) == version
        retrieved = catalog.get("nse-equities", "v1")

        assert retrieved == version
        assert retrieved.identity.metadata == {"a": "1", "b": "2"}
        assert retrieved.identity.fingerprint() == version.identity.fingerprint()


def test_exact_duplicate_registration_is_idempotent(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        first = catalog.register(_version())
        second = catalog.register(_version())

        assert first == second
        assert second == catalog.get("nse-equities", "v1")


def test_same_version_different_source_id_raises(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        catalog.register(_version())

        with pytest.raises(ValueError, match="different identity"):
            catalog.register(_version(source_id="other-venue"))


def test_same_version_different_schema_version_raises(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        catalog.register(_version())

        with pytest.raises(ValueError, match="different identity"):
            catalog.register(_version(schema_version="2"))


def test_same_version_different_content_fingerprint_raises(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        catalog.register(_version())

        with pytest.raises(ValueError, match="different identity"):
            catalog.register(_version(content_fingerprint=fingerprint_bytes(b"other-bytes")))


def test_same_version_different_metadata_raises(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        catalog.register(_version())

        with pytest.raises(ValueError, match="different identity"):
            catalog.register(_version(metadata={"market": "BSE"}))


def test_different_versions_coexist(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        first = catalog.register(_version(version="v1"))
        second = catalog.register(_version(version="v2"))

        assert catalog.get("nse-equities", "v1") == first
        assert catalog.get("nse-equities", "v2") == second


def test_different_dataset_ids_coexist(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        first = catalog.register(_version(dataset_id="nse-equities"))
        second = catalog.register(_version(dataset_id="bse-equities"))

        assert catalog.get("nse-equities", "v1") == first
        assert catalog.get("bse-equities", "v1") == second


def test_lookup_path_is_deterministic(tmp_path) -> None:
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    catalog.register(_version(dataset_id="a/b", version="v 1"))

    expected = tmp_path / "catalog" / "datasets" / "a%2Fb" / "v%201.json"

    assert expected.exists()
    assert catalog.get("a/b", "v 1") is not None


def test_atomic_write_leaves_no_temp_files(tmp_path) -> None:
    root = tmp_path / "catalog"
    catalog = FilesystemDatasetCatalog(root)
    catalog.register(_version())

    leftovers = list(root.rglob("*.tmp"))

    assert leftovers == []


def test_malformed_json_fails_explicitly(tmp_path) -> None:
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    catalog.register(_version())
    target = tmp_path / "catalog" / "datasets" / "nse-equities" / "v1.json"
    target.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed dataset registration"):
        catalog.get("nse-equities", "v1")


def test_missing_required_fields_fail_explicitly(tmp_path) -> None:
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    catalog.register(_version())
    target = tmp_path / "catalog" / "datasets" / "nse-equities" / "v1.json"
    target.write_text('{"dataset_id": "nse-equities"}', encoding="utf-8")

    with pytest.raises(ValueError, match="malformed dataset registration"):
        catalog.get("nse-equities", "v1")


def test_content_fingerprints_remain_exact(tmp_path) -> None:
    fingerprint = fingerprint_bytes(b"exact-bytes-\x00\xff")
    for catalog in _catalogs(tmp_path):
        version = _version(content_fingerprint=fingerprint)
        catalog.register(version)

        retrieved = catalog.get("nse-equities", "v1")

        assert retrieved is not None
        assert retrieved.identity.content_fingerprint == fingerprint


def test_no_float_conversion_in_persisted_payload(tmp_path) -> None:
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    catalog.register(_version(metadata={"price": "0.100000000000000001"}))
    target = tmp_path / "catalog" / "datasets" / "nse-equities" / "v1.json"

    assert '"0.100000000000000001"' in target.read_text(encoding="utf-8")


def test_original_frozen_objects_unmutated(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        version = _version(metadata={"a": "1"})
        snapshot = DatasetVersion(
            identity=DatasetIdentity(
                dataset_id=version.identity.dataset_id,
                version=version.identity.version,
                source_id=version.identity.source_id,
                schema_version=version.identity.schema_version,
                content_fingerprint=version.identity.content_fingerprint,
                metadata=dict(version.identity.metadata),
            ),
            parent_version=version.parent_version,
        )
        catalog.register(version)

        assert version == snapshot


def test_catalog_has_no_broker_or_network_imports() -> None:
    import inspect

    import quantx.research.dataset_catalog as module

    source = inspect.getsource(module).lower()
    for marker in ("dhan", "broker", "socket", "requests", "urlopen", "dhanhq", "http"):
        assert marker not in source, marker


def test_fresh_catalog_returns_none(tmp_path) -> None:
    for catalog in _catalogs(tmp_path):
        assert catalog.get("nse-equities", "v1") is None


def test_filesystem_registration_survives_new_instance(tmp_path) -> None:
    root = tmp_path / "catalog"
    FilesystemDatasetCatalog(root).register(_version())

    retrieved = FilesystemDatasetCatalog(root).get("nse-equities", "v1")

    assert retrieved == _version()
