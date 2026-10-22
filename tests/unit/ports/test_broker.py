"""Neutral broker-contract ownership regressions.

``quantx.ports.broker`` owns the vendor-neutral adapter, capability,
connection, and descriptor contracts only. The receipt-bearing ``BrokerPort``
is execution-owned (``quantx.execution.ports``), and its behavioral
conformance tests live in the execution test mirror.
"""


def test_broker_contracts_are_canonical_in_ports_and_legacy_identity_is_preserved() -> None:
    import quantx.integrations.brokers as legacy
    import quantx.ports.broker as canonical

    names = (
        "BrokerAdapter",
        "BrokerCapability",
        "BrokerConnectionRef",
        "BrokerDescriptor",
        "CapabilitySet",
    )
    for name in names:
        contract = getattr(canonical, name)
        assert contract.__module__ == "quantx.ports.broker"
        assert getattr(legacy, name) is contract
        assert name in canonical.__all__
        assert name in legacy.__all__


def test_ports_layer_exposes_no_execution_receipt_bearing_broker_port() -> None:
    import quantx.ports.broker as canonical

    assert "BrokerPort" not in canonical.__all__
    assert not hasattr(canonical, "BrokerPort")
    assert not hasattr(canonical, "ExecutionReceipt")
