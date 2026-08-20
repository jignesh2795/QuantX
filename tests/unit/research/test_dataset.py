from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes


def test_content_fingerprint_changes_when_source_bytes_change():
    assert fingerprint_bytes(b"a") != fingerprint_bytes(b"b")


def test_dataset_identity_fingerprint_is_order_independent_for_metadata():
    base = dict(dataset_id="btc", version="2026-01", source_id="vendor-x", schema_version="1", content_fingerprint="abc")
    left = DatasetIdentity(**base, metadata={"b": "2", "a": "1"})
    right = DatasetIdentity(**base, metadata={"a": "1", "b": "2"})
    assert left.fingerprint() == right.fingerprint()


def test_dataset_version_key_is_identity_fingerprint():
    identity = DatasetIdentity("btc", "v1", "source", "schema1", "content")
    version = DatasetVersion(identity)
    assert version.version_key == identity.fingerprint()
