# Spec Coverage Self-Review

Date: 2026-04-23
Branch: `feat/call-artifacts-and-delivery`
Commit at review time: d22bca7b8d9f8f4ca6f52b92a325630912e44034
Final test count: 122 passing

## Spec section coverage

| Spec section | Implementation location | Status |
|---|---|---|
| §2 Config schema | `receptionist/config.py` | ✓ |
| §2.1 Languages | `LanguagesConfig` in `config.py` | ✓ |
| §2.1 Channels list (file/email/webhook) | `MessageChannel` discriminated union in `config.py` | ✓ |
| §2.1 Recording | `RecordingConfig` in `config.py` | ✓ |
| §2.1 Transcripts | `TranscriptsConfig` in `config.py` | ✓ |
| §2.1 Email | `EmailConfig`, `EmailSenderConfig` in `config.py` | ✓ |
| §2.1 Retention | `RetentionConfig` in `config.py` | ✓ |
| §2.2 Legacy `delivery` compat | `MessagesConfig.convert_legacy_delivery` validator | ✓ |
| §2.3 Env-var interpolation | `_interpolate_env_vars` in `config.py` | ✓ |
| §3 Package structure | `receptionist/{messaging,email,recording,transcript,retention}/` | ✓ |
| §4.1 Dispatcher (sync-first + background) | `receptionist/messaging/dispatcher.py` | ✓ |
| §4.2 FileChannel | `receptionist/messaging/channels/file.py` | ✓ |
| §4.2 WebhookChannel with retry | `receptionist/messaging/channels/webhook.py` | ✓ |
| §4.2 EmailChannel with retry | `receptionist/messaging/channels/email.py` | ✓ |
| §4.3 EmailSender protocol | `receptionist/email/sender.py` | ✓ |
| §4.3 SMTPSender | `receptionist/email/smtp.py` | ✓ |
| §4.3 ResendSender | `receptionist/email/resend.py` | ✓ |
| §4.4 Recording egress | `receptionist/recording/egress.py` | ✓ |
| §4.4 Recording storage | `receptionist/recording/storage.py` | ✓ |
| §4.5 TranscriptCapture | `receptionist/transcript/capture.py` | ✓ |
| §4.5 CallMetadata | `receptionist/transcript/metadata.py` | ✓ |
| §4.5 Transcript formatters | `receptionist/transcript/formatter.py` | ✓ |
| §4.5 Transcript writer | `receptionist/transcript/writer.py` | ✓ |
| §4.6 CallLifecycle | `receptionist/lifecycle.py` | ✓ |
| §4.6 Close-event future pattern | `handle_call` in `receptionist/agent.py` | ✓ |
| §4.7 Consent preamble before greeting | `Receptionist.on_enter` in `agent.py` | ✓ |
| §4.7 Multi-language system prompt | `_build_language_block` in `prompts.py` | ✓ |
| §5 Error handling (`.failures/` records) | `receptionist/messaging/failures.py` | ✓ |
| §5 `list-failures` CLI | `receptionist/messaging/failures_cli.py` + `__main__.py` | ✓ |
| §5 Retention sweeper | `receptionist/retention/sweeper.py` + `__main__.py` | ✓ |
| §6 Unit tests (one per subpackage) | `tests/{messaging,email,recording,transcript,retention}/` | ✓ |
| §6 Integration test | `tests/integration/test_call_flow.py` | ✓ |
| §6 Manual checklist | `tests/MANUAL.md` | ✓ |
| §7 New dependencies | Added to `pyproject.toml` | ✓ |
| §8 `.python-version` | Present | ✓ |
| §8 `.gitignore` updates | `.worktrees/`, `transcripts/`, `recordings/` added | ✓ |
| §8 Doc updates | `documentation/architecture.md`, `CHANGELOG.md`, `HANDOFF.md` addendum, `README.md` | ✓ |

## Test count progression

| Phase | Cumulative tests |
|---|---|
| Baseline (main) | 15 |
| Phase 1 (config) | 26 |
| Phase 2 (messaging restructure) | 35 |
| Phase 3 (webhook retry) | 45 |
| Phase 4 (email) | 62 |
| Phase 5 (transcripts) | 83 |
| Phase 6 (recording) | 93 |
| Phase 7 (lifecycle integration) | 105 |
| Phase 8 (consent preamble) | 108 |
| Phase 9 (multi-language) | 112 |
| Phase 10 (retention + failures CLI) | 122 |
| Phase 11 (docs only) | 122 |
| Phase 12 (manual + closeout) | 122 |

## Deviations from spec

None found — the spec was followed as written. Several code-review notes caught minor issues during implementation that were fixed inline:

- `_OUTCOME_PRIORITY.get(outcome, 0)` silently dropped unknown outcomes → now raises `ValueError` (commit `b5c390f`)
- `retry_with_backoff` ignored `EmailSendError.retry_after` → now honors it with 60s clamp (commit `95c219b`)
- Dispatcher's background tasks swallowed `CancelledError` and missed `.failures/` writes → now catches + re-raises cleanly (commit `cd8172c`)
- `resolve_failures_dir` fallback used a relative path that depended on cwd → now resolves to absolute (commit `cd8172c`)
- `pytest-mode=importlib` added to `pyproject.toml` so `tests/email/` doesn't shadow stdlib `email` (landed with commit `3208d13`)
- LiveKit's protobuf `EncodedFileOutput.s3` couldn't be assigned post-construction → switched to kwargs (landed with commit `cb0c7e8`)

## Outstanding items

- Task 12.2 (live LiveKit playground walk-through) cannot be automated — requires Kirk to run `tests/MANUAL.md` checklist live before merge.
- None of the spec's "Out of Scope" items were attempted (SMS channel, admin UI, retry CLI for .failures/, structured JSON logging, S3 transcripts).

## Sign-off

Spec coverage: **complete**. Implementation matches spec verbatim with targeted code-review fixes.
Next step: manual validation (Task 12.2), then merge.
