"""Bounded failure-reporting tests for quarantined evidence exceptions."""

from quantx.execution.receipts.quarantine import (
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
)


class _UnprintableIdentity:
    def __str__(self) -> str:
        raise RuntimeError("cannot render")


def test_decode_error_is_robust_and_display_safe_for_hostile_identity() -> None:
    unprintable = QuarantineEvidenceDecodeError(_UnprintableIdentity())
    hostile = QuarantineEvidenceDecodeError("\n\x1b\x00" + "x" * 200)

    assert "<_UnprintableIdentity>" in str(unprintable)
    assert "\n" not in str(hostile)
    assert "\x1b" not in str(hostile)
    assert "\x00" not in str(hostile)
    assert "\\x0a\\x1b\\x00" in str(hostile)
    assert "x" * 100 in str(hostile)
    assert "x" * 200 not in str(hostile)


def test_decode_error_bounded_detail_is_rendered() -> None:
    error = QuarantineEvidenceDecodeError(
        "row-1",
        detail="stored row identity does not match the payload identity",
    )

    assert "row-1" in str(error)
    assert "identity does not match" in str(error)


def test_too_large_error_bounds_identity_and_detail() -> None:
    error = QuarantineEvidenceTooLarge(
        "d" * 2000,
        observation_id="\n\x1b" + "y" * 200,
    )

    assert isinstance(error, RuntimeError)
    assert "\n" not in str(error)
    assert "\x1b" not in str(error)
    assert "d" * 512 in str(error)
    assert "d" * 513 not in str(error)
    assert "y" * 200 not in str(error)
    assert len(str(error)) <= 750
