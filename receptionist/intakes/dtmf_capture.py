# receptionist/intakes/dtmf_capture.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaptureStatus(str, Enum):
    COLLECTING = "collecting"
    COMPLETE = "complete"
    CLEARED = "cleared"


@dataclass
class DigitCaptureBuffer:
    """Pure state machine for collecting DTMF digits from a phone keypad.

    No LiveKit / asyncio — just digit accumulation and termination rules, so
    the logic is trivially unit-testable. Callers feed one keypad key at a
    time via add_key and act on the returned status.

    Termination: `#` completes; reaching `expected_length` (when set)
    auto-completes; `*` clears and restarts. Keys after completion, and
    non-digit/non-control keys, are ignored.
    """

    expected_length: int | None = None
    terminator: str = "#"
    clear_key: str = "*"
    _digits: str = ""
    _complete: bool = False

    @property
    def digits(self) -> str:
        return self._digits

    def add_key(self, key: str) -> CaptureStatus:
        key = (key or "").strip()
        if self._complete:
            return CaptureStatus.COMPLETE
        if key == self.terminator:
            self._complete = True
            return CaptureStatus.COMPLETE
        if key == self.clear_key:
            self._digits = ""
            return CaptureStatus.CLEARED
        if not key.isdigit():
            return CaptureStatus.COLLECTING
        self._digits += key
        if self.expected_length is not None and len(self._digits) >= self.expected_length:
            self._complete = True
            return CaptureStatus.COMPLETE
        return CaptureStatus.COLLECTING
