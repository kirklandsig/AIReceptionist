# receptionist/intakes/__init__.py
"""Structured new-client intake by phone.

The intake feature lets Riley walk a caller through a configurable
question script for a specific case type, persist each answer
incrementally, and email a structured submission at call-end.

Submodules:
  - `models`: dataclasses for IntakeAnswer / IntakeSubmission
  - `storage`: partial + final JSON persistence (atomic writes)

The configuration schema lives in `receptionist.config.IntakesConfig`
and is loaded as `business.intakes` on the top-level `BusinessConfig`.
The tools Riley calls (`record_intake_answer`, `finalize_intake`) live
in `receptionist.agent`.
"""
