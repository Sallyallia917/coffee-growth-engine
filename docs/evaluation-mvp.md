# Evaluation MVP

## Purpose

The evaluation module checks deterministic invariants in the campaign context and
checks whether a generated marketing plan references only eligible products and
coupons. It is a portfolio-stage offline evaluation layer, not proof of increased
conversion, retention, or ROI.

## Current checks

- Required business-context keys and expected structure types
- Audience count consistency
- Recommendations refer only to target audience members
- Coupons marked valid stay within their effective budget and have no remaining rule errors
- Marketing-plan schema and required text fields
- Product and coupon IDs are present in the deterministic context
- Coupon/product compatibility

## Run locally

```bash
python -m pytest -q
```

The initial case catalog is in `evals/cases.jsonl`. It describes target scenarios;
the unit tests in `tests/test_evaluation.py` currently execute representative checks.
The JSONL catalog is not yet an automated runner for every case.

## Baseline comparison: next iteration

Compare two approaches using the same fixed inputs:
1. Rule/template baseline: deterministic audience, product and coupon rules with a fixed template.
2. LLM-assisted plan: the same deterministic context passed to the configured model, followed by output validation.

Record at minimum: case ID, pass/fail, failure category, latency, retry count and model identifier.
Do not report cost unless token usage and the applicable model pricing are actually available.
Do not report conversion, repurchase lift, or ROI without real exposure/order attribution and a suitable comparison design.

## Evidence boundary

The current evaluation functions validate structural and business-rule consistency.
They do not yet measure copy quality, factual grounding beyond IDs/constraints,
human usability, API latency distributions, token cost, or causal business impact.
