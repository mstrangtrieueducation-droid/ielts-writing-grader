# Pro Batch pilot recovery

This transport preserves the Flash notebook gate and the exact Pro two-essay
text-only schema. It changes the transport, not the rubric or student feedback.
No paid QA call, images to Pro, model fallback or truncation to fit a budget.

Google Batch is asynchronous at half Standard token prices. Google targets 24
hours; this is not a deadline guarantee and Batch jobs can fail. Pro 3.1 input /
output (including thinking) under 200k context are $1 / $6 per million tokens in
Batch. The application uses a dated price snapshot and a conservative reserve;
neither an estimate nor a reserve is a confirmed Google charge.

Official references checked 2026-10-11:
- https://ai.google.dev/gemini-api/docs/batch-api
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/generate-content/flex-inference

## Explicit manual submission

Prepare an independently verified, cached notebook and a new audited pilot
binding. Failed historical pilots are immutable and cannot be resubmitted.
Do not activate a new private binding or increase a ceiling before approval.
Run dedicated Actions `mode=pilot`, `authorized_pro_batch_trial=true` only for
the approved exact one-student selection. The trial cap and cumulative student
cap include historical unresolved reserves; retain production OFF and defaults.
The provider SDK create request retries once total, with no Standard fallback.

Before create, the cost reserve and deterministic submission intent are persisted
on private Drive. A network timeout or crash leaves an uncertain intent. A resume
lists provider jobs and matches the exact display name and model; it never
creates another Batch if no match is visible or identity is ambiguous. Manual
reconciliation is required if an intent cannot be identified. A checkpoint crash
between reserve and intent similarly holds the reservation, without resubmitting.

## Read-only collection

Run Actions `mode=collect-pro-batch`, all paid authorization inputs false.
Generation is forced OFF. Collection uses frozen text and the cached passed
notebook, without reading Form responses or downloading student PDFs. It calls
only list/get for the saved Batch, and saves raw output / usage before validation.
Keep collecting the same job while pending. Success must have the saved model,
name, request metadata, exactly one response, normal STOP finish and valid JSON.
Partial, failed or invalid responses remain held; they never trigger regeneration.

Validated output remains a private pilot awaiting independent source-based QA.
The existing `deliver-pilot` flow requires exact payload approval, current source
and original receipt revalidation, then actual dashboard UI and exact tracker
readback. Batch completion alone cannot publish or claim grading completion.

Only one serialized workflow mutates the private ledger. Do not submit through
local Python or bypass GitHub Actions checks. Collection does not automatically
authorize a new Batch. No recurring collection or grading is activated by this
code change; the production switches remain independently controlled.

## Separately approved immediate Standard pilot

The teacher can instead approve `authorized_pro_standard_trial=true` for an
immediate Standard request. This never submits Batch and does not raise global
budgets or enable scheduled generation. Frozen `generation_plan` is required
before selecting `pro_output_limit=16384`; it must record Standard Pro, medium
thinking and that output limit. The new pilot must have its own cost ceiling.
The limit includes BOTH internal thinking and the final structured feedback;
an 8192-token limit can exhaust its allowance on thinking before finishing two
essays. Check the conservative full reserve before any notebook generation.

Preserve a truncated response and its usage before validation. A non-STOP finish
is held even if JSON happens to be parseable. A paid replacement requires a new
teacher-approved attempt, never a loop or a repair of the student's feedback.
Increasing output room preserves the same rubric and thinking level; it does
not certify quality. Independent review and exact delivery checks still apply.
