# Research Provenance and Fingerprints

## Purpose

Every research run must have a deterministic identity derived from the material inputs that can affect its result.

## Fingerprint inputs

The canonical provenance record includes:

```text
Dataset ID/version
Instrument master version
Market rule version
Execution model version
Simulation profile
Code revision
Configuration revision
Random seed (when applicable)
Additional declared inputs
```

## Rules

1. Canonical serialization must be deterministic.
2. Mapping key order must not affect the fingerprint.
3. Any material input change must change the fingerprint.
4. The fingerprint is an identity/checksum, not proof that the underlying data is truthful.
5. Source data and artifacts must remain separately retrievable.
6. An AI/LLM may explain a provenance record but cannot modify it after the run has been recorded.

## Result identity

```text
ResearchResult
      +
ResearchProvenance fingerprint
      ↓
Reproducibility identity
```

A result comparison should surface provenance differences before comparing headline metrics.
