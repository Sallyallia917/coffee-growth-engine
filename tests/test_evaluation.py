import pytest

from services.evaluation import (
    evaluate_business_rules,
    evaluate_marketing_plan,
    evaluate_run,
    summarize_evaluations,
)


def context():
    return {
        "campaign": {"goal": "提升复购", "budget": 100},
        "audience": {
            "eligible_member_count": 1,
            "members": [{"member_id": "M001"}],
        },
        "recommendations": [{
            "member_id": "M001",
            "products": [{"product_id": "P001", "product_name": "拼配豆"}],
        }],
        "coupon_options": [{
            "coupon_id": "C001",
            "valid": True,
            "estimated_coupon_cost": 20,
            "effective_budget_limit": 100,
            "errors": [],
            "single_item_eligible_product_ids": ["P001"],
        }],
    }


def plan(**overrides):
    value = {
        "campaign_title": "咖啡会员复购活动",
        "strategy": "面向目标会员推荐合适商品",
        "copywriting": "选一杯喜欢的风味，开启轻松咖啡时光。",
        "channels": ["微信"],
        "recommended_product_ids": ["P001"],
        "selected_coupon_ids": ["C001"],
        "compliance_notes": ["最终优惠资格以结算校验为准"],
    }
    value.update(overrides)
    return value


def test_evaluates_valid_business_context():
    result = evaluate_business_rules(context())
    assert result["passed"] is True
    assert result["passed_checks"] == result["total_checks"]


def test_detects_audience_count_mismatch():
    data = context()
    data["audience"]["eligible_member_count"] = 2
    result = evaluate_business_rules(data)
    assert result["passed"] is False
    assert next(c for c in result["checks"] if c["name"] == "audience_count_consistency")["passed"] is False


def test_rejects_coupon_over_budget_even_if_marked_valid():
    data = context()
    data["coupon_options"][0]["estimated_coupon_cost"] = 120
    result = evaluate_business_rules(data)
    assert result["passed"] is False


def test_evaluates_valid_marketing_plan():
    result = evaluate_marketing_plan(plan(), context())
    assert result["passed"] is True


@pytest.mark.parametrize("overrides", [
    {"recommended_product_ids": ["P999"]},
    {"selected_coupon_ids": ["C999"]},
    {"selected_coupon_ids": ["C001", "C001"]},
    {"campaign_title": ""},
])
def test_detects_invalid_plan(overrides):
    result = evaluate_marketing_plan(plan(**overrides), context())
    assert result["passed"] is False


def test_rejects_coupon_that_does_not_match_selected_product():
    data = context()
    data["coupon_options"][0]["single_item_eligible_product_ids"] = ["P999"]
    assert evaluate_marketing_plan(plan(), data)["passed"] is False


def test_evaluate_run_records_failure_and_latency():
    result = evaluate_run({
        "run_id": "run-001", "context": context(), "plan": plan(), "latency_ms": 123,
    })
    assert result["status"] == "passed"
    assert result["latency_ms"] == 123


def test_summarizes_case_results_without_dividing_by_zero():
    assert summarize_evaluations([])["pass_rate"] == 0.0
    assert summarize_evaluations([{"passed": True}, {"passed": False}]) == {
        "total_cases": 2, "passed_cases": 1, "failed_cases": 1, "pass_rate": 0.5,
    }
