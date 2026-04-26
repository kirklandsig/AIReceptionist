# Spec coverage self-review — Google Calendar integration

Date: 2026-04-24
Branch: `feat/google-calendar-integration`
HEAD SHA at review time: `a4a2537`
Final test count: **184 passed, 2 skipped on Windows**

## Coverage

| Spec section | Implementation | Status |
|---|---|---|
| §2.1 calendar YAML section | `receptionist/config.py` (CalendarConfig) | ✓ |
| §2.1 auth discriminator | `receptionist/config.py` (ServiceAccountAuth, OAuthAuth) | ✓ |
| §2.1 buffer_placement (before/after/both) | `receptionist/booking/availability.py::_apply_buffer` | ✓ |
| §2.2 on_booking trigger | `receptionist/config.py` EmailTriggers + `lifecycle.py` fan-out | ✓ |
| §2.3 Pydantic models (Service/OAuth, CalendarAuth, CalendarConfig) | `receptionist/config.py` | ✓ |
| §2.4 validation rules (gt=0, ge=0, file existence) | `receptionist/config.py` Field constraints + `validate_auth_file_exists` | ✓ |
| §2.5 cross-section validator (on_booking requires calendar enabled) | `receptionist/config.py::validate_cross_section` | ✓ |
| §2.6 outcomes breaking change (str → set[str]) | Phase 1 (commit `8ad9da5` + polish `e1ccf03`) | ✓ |
| §2.7 env-var interpolation (existing pattern) | Already shipped in PR #2; calendar uses files for keys | N/A |
| §3 package structure | `receptionist/booking/{models,auth,client,availability,booking,setup_cli}.py` + `__main__.py` | ✓ |
| §3.1 component boundaries | `auth.py` builds creds; `client.py` wraps Google API; `availability.py` is pure; `booking.py` orchestrates | ✓ |
| §4.1 check_availability flow | `agent.py::Receptionist.check_availability` + `availability.find_slots` | ✓ |
| §4.1 book_appointment flow | `agent.py::Receptionist.book_appointment` + `booking.book_appointment` | ✓ |
| §4.2 session-scoped slot cache | `Receptionist._offered_slots: set[str]` (init in `__init__`, populated in `check_availability`, validated in `book_appointment`) | ✓ |
| §4.3 CallMetadata new fields (appointment_booked, appointment_details) | `receptionist/transcript/metadata.py` | ✓ |
| §4.5 on_booking trigger fan-out | `lifecycle.py::on_call_ended` + `_fire_booking_email` | ✓ |
| §4.6 multi-outcome templates | `email/templates.py::_outcomes_display` + `transcript/formatter.py` | ✓ |
| §5 error handling per component | Per-tool try/except with graceful fallback strings; `CalendarAuthError`, `SlotNoLongerAvailableError`, race recovery | ✓ |
| §5.1 race detection | `booking/booking.py` re-queries free_busy before create_event | ✓ |
| §5.2 not-retried list | No retry on auth errors; client errors return None / fallback strings | ✓ |
| §5.3 logging contract | All failure logs use `extra={call_id, business_name, component}` | ✓ |
| §5.4 security behavior | `booking/auth.py::_check_token_permissions` (0600 enforce on Unix); never-log-keys discipline; UNVERIFIED tag in events | ✓ |
| §6 unit tests per subpackage | `tests/booking/{test_auth,test_client,test_availability,test_booking,test_setup_cli}.py` + `tests/test_prompts.py` + `tests/email/test_templates.py` + `tests/test_lifecycle.py` + `tests/transcript/test_metadata.py` | ✓ |
| §6 integration test | `tests/integration/test_booking_flow.py` (4 scenarios) | ✓ |
| §7 new deps | `pyproject.toml`: google-api-python-client, google-auth, google-auth-oauthlib, python-dateutil | ✓ |
| §8 secrets directory | `secrets/.gitkeep` + `.gitignore` negation pattern | ✓ |
| §8 setup CLI | `receptionist/booking/setup_cli.py` + `__main__.py` | ✓ |
| §8 docs (setup guide) | `documentation/google-calendar-setup.md` | ✓ |
| §9 rollout sequencing (13 phases) | All 13 phases executed in order (0,1,2,3,4,5,6,7,8,9,10,11,12,13) | ✓ |

## Code-review fixes that landed inline during execution

These came from the two-stage subagent review process and were addressed before phase completion:

- **Phase 1 polish** (commit `e1ccf03`):
  - Restored type annotations dropped during the outcomes refactor (`_outcomes_display`, `_format_duration`, three inner `e()` helpers in `email/templates.py`)
  - Tightened dead-branch test assertion (`"UNVERIFIED" in body or "was NOT verified" in body` → just `"was NOT verified"`)
  - Added invariant test that `_OUTCOME_LABELS.keys() == VALID_OUTCOMES` so future drift fails the suite
  - Added regression tests: `_add_outcome` does not "demote" outcomes, and `appointment_booked` bool stays in sync with the outcomes set
- **Phase 6 polish** (commit `444d63a`): added a partial-overlap race detection test (existing test only covered exact-match)
- **Phase 8 polish** (commit `7ee442b`): type annotation on `_format_friendly_date(dt: datetime)`, comment explaining deferred imports, comment documenting the cache-reset trade-off in race recovery

## Outstanding items

- **Task 13.1** (live LiveKit playground walk-through): cannot be automated. Requires a real Google Calendar test account + a real call through the LiveKit playground. The full checklist is at `tests/MANUAL.md` under "Calendar integration (issue #3)".

## Sign-off

**Spec coverage: complete.**

All 13 phases of the implementation plan executed. 184 tests passing (+ 2 Windows-skipped POSIX-permission checks, intentional). Every spec section traced to its implementation file/commit. Three rounds of inline code-review polish landed (phases 1, 6, 8) before phase completion — none were blocking issues, all were quality improvements caught by subagent code reviewers.

**Next step:** Task 13.1 manual validation against a live Google Calendar test account, then merge to main.

## Branch + push state

Branch: `feat/google-calendar-integration` on origin
Latest commit: `a4a2537` (docs: full docs sweep for Google Calendar integration)
21 commits ahead of main.
