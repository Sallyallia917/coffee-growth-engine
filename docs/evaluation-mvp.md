# Evaluation MVP

## Purpose

The evaluation layer checks deterministic invariants in campaign context and
whether a marketing plan references eligible products and coupons. It is an
offline portfolio evaluation, not evidence of increased conversion, retention, or ROI.

## Run locally

```bash
python -m pytest -q
python -m evals.run_evaluation
```

The runner reads `evals/cases.jsonl`, executes each named scenario against a
fixed synthetic context, checks actual evaluator behavior against the expected
pass/fail outcome, and writes:
- `evals/results.json`: machine-readable report
- `evals/report.md`: human-readable report

The suite does not call DeepSeek or any live API. It verifies that the evaluator
detects deliberately constructed pass/fail cases; it does not yet measure the
model's copy quality or compare model output with a template baseline.

## Current checks

- Required business-context keys and expected structure types
- Audience count consistency
- Recommendations refer only to target audience members
- Coupons marked valid stay within effective budget and have no remaining rule errors
- Marketing-plan schema and required text fields
- Product and coupon IDs refer to deterministic context
- Coupon/product compatibility
- API-error run records are not treated as successful plans

## Next iteration: baseline comparison

Compare two approaches using the same fixed inputs:
1. Rule/template baseline: deterministic audience, product and coupon rules with a fixed template.
2. LLM-assisted plan: the same deterministic context passed to the configured model, followed by output validation.

Record case ID, pass/fail, failure category, latency, retry count and model identifier.
Do not report cost unless token usage and applicable model pricing are available.
Do not report conversion, repurchase lift, or ROI without real exposure/order attribution
and a suitable comparison design.

## Evidence boundary

The current suite validates evaluator behavior on synthetic fixtures. It does not
yet measure marketing copy quality, human usability, model API latency distributions,
token cost, or causal business impact.
