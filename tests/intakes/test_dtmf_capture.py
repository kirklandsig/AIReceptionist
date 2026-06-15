# tests/intakes/test_dtmf_capture.py
from __future__ import annotations

from receptionist.intakes.dtmf_capture import CaptureStatus, DigitCaptureBuffer


def test_digits_accumulate_and_terminate_on_hash():
    buf = DigitCaptureBuffer()
    assert buf.add_key("6") == CaptureStatus.COLLECTING
    assert buf.add_key("3") == CaptureStatus.COLLECTING
    assert buf.add_key("1") == CaptureStatus.COLLECTING
    assert buf.add_key("#") == CaptureStatus.COMPLETE
    assert buf.digits == "631"


def test_auto_completes_at_expected_length():
    buf = DigitCaptureBuffer(expected_length=4)
    assert buf.add_key("1") == CaptureStatus.COLLECTING
    assert buf.add_key("2") == CaptureStatus.COLLECTING
    assert buf.add_key("3") == CaptureStatus.COLLECTING
    assert buf.add_key("4") == CaptureStatus.COMPLETE
    assert buf.digits == "1234"


def test_star_clears_and_restarts():
    buf = DigitCaptureBuffer()
    buf.add_key("9")
    buf.add_key("9")
    assert buf.add_key("*") == CaptureStatus.CLEARED
    assert buf.digits == ""
    buf.add_key("1")
    assert buf.add_key("#") == CaptureStatus.COMPLETE
    assert buf.digits == "1"


def test_over_length_digits_ignored_after_autocomplete():
    buf = DigitCaptureBuffer(expected_length=2)
    buf.add_key("1")
    assert buf.add_key("2") == CaptureStatus.COMPLETE
    assert buf.add_key("3") == CaptureStatus.COMPLETE
    assert buf.digits == "12"


def test_non_digit_non_control_key_ignored():
    buf = DigitCaptureBuffer()
    buf.add_key("6")
    assert buf.add_key("A") == CaptureStatus.COLLECTING
    assert buf.digits == "6"


def test_hash_on_empty_completes_empty():
    buf = DigitCaptureBuffer()
    assert buf.add_key("#") == CaptureStatus.COMPLETE
    assert buf.digits == ""
