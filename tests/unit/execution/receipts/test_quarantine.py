"""Bounded failure-reporting and display-neutralization tests for quarantine evidence."""

import pytest

from quantx.execution.receipts.quarantine import (
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
    QuarantineEvidenceUnavailable,
    neutralize_display_text,
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
    assert "\\n\\x1b\\x00" in str(hostile)
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


def test_unavailable_error_message_is_static_and_bounded() -> None:
    error = QuarantineEvidenceUnavailable(
        "database is locked: FILE:/tmp/secret/evidence.db " + "z" * 2000
    )
    message = str(error)

    assert message.startswith("quarantine evidence store could not be read: ")
    assert "database is locked" in message
    assert "z" * 450 in message
    assert len(message) < 600


def test_display_neutralization_escapes_bidi_formatting_controls() -> None:
    bidi = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

    rendered = neutralize_display_text(f"before{bidi}after", max_length=512)

    for character in bidi:
        assert character not in rendered
    for codepoint in (0x061C, 0x200E, 0x200F, 0x202E, 0x2066, 0x2069):
        assert f"\\u{codepoint:04x}" in rendered
    assert rendered.startswith("before")
    assert rendered.endswith("after")


def test_display_neutralization_escapes_lone_surrogates_safely() -> None:
    rendered = neutralize_display_text("a\ud800b\udfffc", max_length=64)

    assert "\ud800" not in rendered
    assert "\udfff" not in rendered
    assert rendered == "a\\ud800b\\udfffc"
    # The neutralized copy is always terminal-encodable.
    assert rendered.encode("utf-8") == b"a\\ud800b\\udfffc"


def test_display_neutralization_escapes_line_separators_and_c1_controls() -> None:
    rendered = neutralize_display_text("a\u2028b\u2029c\x85d\x9be", max_length=64)

    assert rendered == "a\\u2028b\\u2029c\\x85d\\x9be"
    for character in ("\u2028", "\u2029", "\x85", "\x9b"):
        assert character not in rendered


def test_display_neutralization_keeps_printable_unicode_and_bounds_output() -> None:
    assert neutralize_display_text("caf\u00e9 \u20b9", max_length=32) == "caf\u00e9 \u20b9"

    rendered = neutralize_display_text("\x1b" * 100, max_length=32)

    assert len(rendered) == 32
    assert rendered.endswith("...")
    assert "\x1b" not in rendered


@pytest.mark.parametrize("max_length", [0, -1])
def test_display_neutralization_rejects_non_positive_bounds(max_length: int) -> None:
    with pytest.raises(ValueError, match="max_length"):
        neutralize_display_text("text", max_length=max_length)
