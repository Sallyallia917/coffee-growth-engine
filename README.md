# Coffee Growth Engine

## Deterministic campaign business flow

`services.campaign_service.build_campaign_context` combines the existing
segmentation, product recommendation, and coupon validation rules. It does not
call an LLM; its result is a structured, JSON-compatible context for a later
generation step.

```python
import csv
from pathlib import Path

from services.campaign_service import build_campaign_context


def load_records(filename):
    with (Path("data") / filename).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


context = build_campaign_context(
    campaign_request={
        "goal": "提升复购",
        "budget": 1000,
        # Optional: "target_segment": "沉睡待唤醒",
        # Optional: "coupon_id": "C001",
        # Optional: "expected_redemption_rate": 0.3,
    },
    members=load_records("members.csv"),
    products=load_records("products.csv"),
    coupons=load_records("coupons.csv"),
)
```

The required request fields are `goal` and `budget`. The service selects only
members who consented to marketing, then optionally filters them to an exact
`target_segment`. Recommendations and segmentation use the existing functions
in `core/`; a specified coupon ID evaluates only that coupon, while omitting it
returns evaluations for all supplied coupons.

Coupon cost estimates use the selected audience size and expected redemption
rate and must fit both the coupon budget and campaign budget. The single-item
eligibility result compares each recommended product's price with the coupon's
minimum spend and validates its discounted margin. Whether a multi-item cart
meets the coupon threshold requires the actual order total and is intentionally
left for checkout-time validation.

The current member data fields are `member_id`, `preferred_category`,
`days_since_last_order`, `order_count`, and `consent_marketing` (the dataset also
contains `member_name` and `total_spend`). Product fields are `product_id`,
`product_name`, `category`, `price`, `cost`, and `stock`. Coupon fields are
`coupon_id`, `coupon_name`, `min_spend`, `discount`, `budget`, and `valid_days`.
Orders are not used by the current segmentation or recommendation rules.

Run deterministic tests with:

```bash
python -m pytest -q
```

Start the Streamlit interface from the project root with:

```bash
streamlit run app.py
```

The page reads `data/members.csv`, `data/products.csv`, and `data/coupons.csv`.
Submit the form to calculate the deterministic business results. The DeepSeek
call can be disabled to inspect those results without using the API; when it is
enabled, API and response-validation errors are shown while business results
remain visible.

## DeepSeek marketing plan generation

The deterministic result can be passed to
`services.llm_service.generate_marketing_plan(context)`. Configure the
OpenAI-compatible DeepSeek endpoint in a local `.env` file (copy
`.env.example` to `.env` and set `DEEPSEEK_API_KEY`), or provide the variables
through the process environment. Supported settings are:

- `DEEPSEEK_API_KEY` (required; never commit the real value)
- `DEEPSEEK_BASE_URL` (defaults to `https://api.deepseek.com`)
- `DEEPSEEK_MODEL` (defaults to `deepseek-chat`)
- `DEEPSEEK_TIMEOUT_SECONDS` (defaults to `30`)

Use the business service first, then pass its result to the LLM service:

```python
import csv
from pathlib import Path

from services.campaign_service import build_campaign_context
from services.llm_service import generate_marketing_plan


def load_records(filename):
    with (Path("data") / filename).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


business_context = build_campaign_context(
    campaign_request={"goal": "提升复购", "budget": 1000},
    members=load_records("members.csv"),
    products=load_records("products.csv"),
    coupons=load_records("coupons.csv"),
)
marketing_plan = generate_marketing_plan(business_context)
print(marketing_plan)
```

Do not call `generate_marketing_plan({})`: an API key only authenticates the
remote request; it does not create the campaign, audience, recommendations, or
coupon checks. The function requires the complete business context returned by
`build_campaign_context`.

The service sends the campaign request, audience counts, recommended product
details, and only coupons that passed deterministic validation and apply to at
least one recommended product. If none qualify, it sends an empty coupon list
and expects a coupon-free plan. It omits individual member records and
identifiers. The returned JSON object has `campaign_title`, `strategy`,
`copywriting`, `channels`, `recommended_product_ids`, `selected_coupon_ids`,
and `compliance_notes`. The service rejects malformed output, unknown product
IDs, coupons that failed deterministic validation, coupon/product combinations
that do not match, and unsupported numeric claims in generated text. Numbers
are allowed in marketing text only when they occur inside the exact name of a
product and coupon selected in the plan. Unsupported numbers are reported with
their output field, and the service asks the model to correct the plan once.
If the retry is still invalid, the service raises an error instead of returning
it.

Configuration, network/HTTP, empty response, and invalid-output failures raise
specific `LLMServiceError` subclasses with user-readable messages. No success-
shaped fallback is returned if the model is unavailable; the deterministic
business context remains available to display independently.