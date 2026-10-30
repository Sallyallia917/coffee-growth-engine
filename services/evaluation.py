"""Lightweight deterministic evaluation helpers for Coffee Growth Engine.

These checks evaluate application business context and generated plans. They do not
replace human review or real-world marketing experiments.
"""
from collections.abc import Mapping, Sequence
from typing import Any

PLAN_FIELDS = {
    "campaign_title", "strategy", "copywriting", "channels",
    "recommended_product_ids", "selected_coupon_ids", "compliance_notes",
}


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(item["passed"] for item in checks)
    total = len(checks)
    return {"passed": passed == total, "passed_checks": passed,
            "total_checks": total, "checks": checks}


def evaluate_business_rules(context: Mapping[str, Any]) -> dict[str, Any]:
    """Check invariants in build_campaign_context output without calling an LLM."""
    required = {"campaign", "audience", "recommendations", "coupon_options"}
    missing = sorted(required - set(context))
    checks = [_check("context_schema", not missing,
                     "业务上下文包含必需字段" if not missing else f"缺少字段：{', '.join(missing)}")]
    if missing:
        return _result(checks)

    campaign, audience = context["campaign"], context["audience"]
    recommendations, coupons = context["recommendations"], context["coupon_options"]
    valid_types = (
        isinstance(campaign, Mapping) and isinstance(audience, Mapping)
        and isinstance(recommendations, Sequence) and not isinstance(recommendations, (str, bytes))
        and isinstance(coupons, Sequence) and not isinstance(coupons, (str, bytes))
    )
    checks.append(_check("context_types", valid_types,
                         "活动、受众、推荐和优惠券结构类型有效" if valid_types else "上下文结构类型不正确"))
    if not valid_types:
        return _result(checks)

    members = audience.get("members", [])
    count = audience.get("eligible_member_count")
    count_ok = (isinstance(members, Sequence) and not isinstance(members, (str, bytes))
                and isinstance(count, int) and count == len(members))
    checks.append(_check("audience_count_consistency", count_ok,
                         "目标会员人数与会员明细一致" if count_ok else "目标会员人数与会员明细不一致"))

    member_ids = {m.get("member_id") for m in members if isinstance(m, Mapping)}
    recommendation_ids = [r.get("member_id") for r in recommendations if isinstance(r, Mapping)]
    recommendations_match = (
        len(recommendation_ids) == len(recommendations)
        and len(recommendation_ids) == len(set(recommendation_ids))
        and set(recommendation_ids).issubset(member_ids)
    )
    checks.append(_check("recommendation_audience_consistency", recommendations_match,
                         "推荐对象均来自目标会员且没有重复" if recommendations_match
                         else "推荐对象与目标会员不一致或存在重复"))

    invalid_budget_ids, coupons_with_errors = [], []
    for coupon in coupons:
        if not isinstance(coupon, Mapping):
            invalid_budget_ids.append("<invalid-record>")
            continue
        if coupon.get("valid") is True:
            try:
                within_budget = float(coupon["estimated_coupon_cost"]) <= float(coupon["effective_budget_limit"])
            except (KeyError, TypeError, ValueError):
                within_budget = False
            if not within_budget:
                invalid_budget_ids.append(str(coupon.get("coupon_id", "<unknown>")))
            if coupon.get("errors"):
                coupons_with_errors.append(str(coupon.get("coupon_id", "<unknown>")))
    checks.append(_check("valid_coupon_budget", not invalid_budget_ids,
                         "所有有效优惠券均未超过有效预算" if not invalid_budget_ids
                         else f"有效优惠券预算校验异常：{', '.join(invalid_budget_ids)}"))
    checks.append(_check("valid_coupon_has_no_errors", not coupons_with_errors,
                         "有效优惠券没有遗留校验错误" if not coupons_with_errors
                         else f"有效优惠券仍包含错误：{', '.join(coupons_with_errors)}"))
    return _result(checks)


def evaluate_marketing_plan(plan: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Check generated plan schema and references against deterministic business results."""
    schema_ok = isinstance(plan, Mapping) and set(plan) == PLAN_FIELDS
    checks = [_check("plan_schema", schema_ok,
                     "营销方案字段符合约定结构" if schema_ok else "字段缺失、多余或响应不是对象")]
    if not schema_ok:
        return _result(checks)

    text_ok = all(isinstance(plan.get(f), str) and bool(plan[f].strip())
                  for f in ("campaign_title", "strategy", "copywriting"))
    checks.append(_check("required_text_fields", text_ok,
                         "标题、策略和文案均为非空文本" if text_ok else "标题、策略或文案为空或类型不正确"))
    lists_ok = all(isinstance(plan.get(f), list) for f in
                   ("channels", "recommended_product_ids", "selected_coupon_ids", "compliance_notes"))
    checks.append(_check("list_fields", lists_ok,
                         "渠道、商品、优惠券和合规说明均为列表" if lists_ok else "一个或多个列表字段类型不正确"))
    if not lists_ok:
        return _result(checks)

    recommendations = context.get("recommendations", [])
    available_products = {
        p.get("product_id") for row in recommendations if isinstance(row, Mapping)
        for p in row.get("products", []) if isinstance(p, Mapping)
    }
    selected_products = plan["recommended_product_ids"]
    products_ok = (all(isinstance(x, str) for x in selected_products)
                   and len(selected_products) == len(set(selected_products))
                   and set(selected_products).issubset(available_products))
    checks.append(_check("product_references", products_ok,
                         "方案商品均来自业务推荐结果且无重复" if products_ok else "方案包含未知或重复商品编号"))

    eligible_coupons = {
        c.get("coupon_id"): c for c in context.get("coupon_options", [])
        if isinstance(c, Mapping) and c.get("valid") is True and isinstance(c.get("coupon_id"), str)
    }
    selected_coupons = plan["selected_coupon_ids"]
    coupons_ok = (all(isinstance(x, str) for x in selected_coupons)
                  and len(selected_coupons) == len(set(selected_coupons))
                  and set(selected_coupons).issubset(eligible_coupons))
    checks.append(_check("coupon_references", coupons_ok,
                         "方案优惠券均通过业务规则校验且无重复" if coupons_ok
                         else "方案包含未通过校验或未知的优惠券编号"))

    compatible = True
    for coupon_id in selected_coupons:
        coupon = eligible_coupons.get(coupon_id)
        if coupon is None or not set(coupon.get("single_item_eligible_product_ids", [])).intersection(selected_products):
            compatible = False
            break
    checks.append(_check("coupon_product_compatibility", compatible,
                         "所选优惠券至少适用于一个所选商品" if compatible
                         else "所选优惠券与方案商品不匹配"))
    return _result(checks)


def evaluate_run(run_record: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one normalized run record; API invocation is intentionally external."""
    context, plan, error = run_record.get("context"), run_record.get("plan"), run_record.get("error")
    context_result = (evaluate_business_rules(context) if isinstance(context, Mapping)
                      else _result([_check("context_present", False, "运行记录缺少有效业务上下文")]))
    plan_result = (evaluate_marketing_plan(plan, context)
                   if isinstance(context, Mapping) and plan is not None and not error
                   else _result([_check("plan_available", False, str(error or "没有可评测的营销方案"))]))
    passed = context_result["passed"] and plan_result["passed"]
    return {"run_id": run_record.get("run_id"), "status": "passed" if passed else "needs_review",
            "latency_ms": run_record.get("latency_ms"), "business_rules": context_result,
            "marketing_plan": plan_result}


def summarize_evaluations(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate case outcomes; does not imply real-world business uplift."""
    total = len(results)
    passed = sum(1 for item in results if item.get("passed") is True)
    return {"total_cases": total, "passed_cases": passed, "failed_cases": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0}
