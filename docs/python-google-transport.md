# IELTS Python I/O and private checkpoints

Production Form reads and tracker writes use `SheetService` with the existing clean `GCP_SA_KEY`. The production entrypoint no longer authenticates checkpoint storage with `GOOGLE_STATE_OAUTH_JSON` or calls a deployed Apps Script.

Set `IELTS_STATE_SPREADSHEET_ID` to the private control spreadsheet provisioned during the verified migration. Its hidden `_IELTS_PYTHON_STATE_V1` tab contains checksum-bound JSON chunks. Hidden is a display setting: confidentiality comes from the spreadsheet's existing restricted Drive permissions. The runner checks those permissions before grading.

The migration imports every historical JSON record before adding a completion manifest. Original Drive IDs remain aliases, preserving job IDs, saved responses, returned results and cumulative cost ledgers. There is no automatic reset, rescan, regrade or fallback to old-user OAuth. Keep the original private source files as recovery evidence.

`SheetsStateDrive` retains the existing StateStore/CostLedger interface and repository concurrency group. Each mutation is atomic and checked by exact readback, including recovery of a lost response without replay. Incomplete chunks, checksum failure, an absent migration marker or a concurrent writer stop the grading run before a new charge.

The original model, activation flags, budget limits, source gates, notebook locks, delivery checks and schedules remain unchanged. This transport migration does not authorize enabling a previously disabled grading workflow.

Tests: `python -m pytest tests/test_sheets_state.py`. Actual connection probes use private dedicated cells, never fabricated grades or modifications to student submission cells.
