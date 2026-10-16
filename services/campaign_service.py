from collections import Counter
from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from core.coupon_rules import validate_campaign
from core.recommendation import recommend_products
from core.segmentation import segment_member


def _require_fields(
    record: Mapping[str, Any],
    fields: Sequence[str],
    record_name: str,
) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(
            f"{record_name}缺少必需字段: {', '.join(missing)}"
        )


def _validate_records(
    records: Sequence[Mapping[str, Any]],
    record_name: str,
) -> None:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ValueError(f"{record_name}数据必须是记录列表")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"{record_name}第 {index + 1} 条数据必须是对象")


def _validate_campaign_request(
    campaign_request: Mapping[str, Any],
) -> tuple[str, float, str | None, str | None, float]:
    _require_fields(campaign_request, ("goal", "budget"), "活动需求")

    goal = campaign_request["goal"]
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("活动目标必须是非空字符串")

    try:
        budget = float(campaign_request["budget"])
        redemption_rate = float(
            campaign_request.get("expected_redemption_rate", 0.3)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("预算和预计核销率必须是数字") from exc

    if not isfinite(budget) or budget < 0:
        raise ValueError("预算必须是大于或等于 0 的有限数字")
    if not isfinite(redemption_rate) or not 0 <= redemption_rate <= 1:
        raise ValueError("预计核销率必须是 0 到 1 之间的有限数字")

    target_segment = campaign_request.get("target_segment")
    if target_segment is not None and not isinstance(target_segment, str):
        raise ValueError("目标会员分群必须是字符串")

    coupon_id = campaign_request.get("coupon_id")
    if coupon_id is not None and not isinstance(coupon_id, str):
        raise ValueError("优惠券编号必须是字符串")

    return goal.strip(), budget, target_segment, coupon_id, redemption_rate


def _evaluate_coupon(
    coupon: Mapping[str, Any],
    products: Sequence[Mapping[str, Any]],
    audience_size: int,
    campaign_budget: float,
    redemption_rate: float,
) -> dict[str, Any]:
    _require_fields(
        coupon,
        ("coupon_id", "coupon_name", "min_spend", "discount", "budget", "valid_days"),
        "优惠券",
    )
    try:
        min_spend = float(coupon["min_spend"])
        coupon_budget = float(coupon["budget"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"优惠券 {coupon['coupon_id']} 的门槛或预算必须是数字"
        ) from exc

    effective_budget = min(coupon_budget, campaign_budget)
    validation = validate_campaign(
        {**coupon, "budget": effective_budget},
        audience_size=audience_size,
        expected_redemption_rate=redemption_rate,
    )

    product_validations = []
    for product in products:
        _require_fields(
            product,
            ("product_id", "product_name", "category", "price", "cost", "stock"),
            "商品",
        )
        price = float(product["price"])
        if price < min_spend:
            continue
        product_validation = validate_campaign(
            {**coupon, "budget": effective_budget},
            audience_size=audience_size,
            expected_redemption_rate=redemption_rate,
            product=product,
        )
        product_validations.append({
            "product_id": product["product_id"],
            "product_name": product["product_name"],
            "valid": product_validation["valid"],
            "errors": product_validation["errors"],
        })

    single_item_eligible = [
        item["product_id"] for item in product_validations if item["valid"]
    ]
    errors = list(validation["errors"])
    if not product_validations:
        errors.append("没有推荐商品的单件售价达到优惠门槛")
    elif not single_item_eligible:
        errors.append("达到优惠门槛的推荐商品均未通过折后毛利校验")

    return {
        "coupon_id": coupon["coupon_id"],
        "coupon_name": coupon["coupon_name"],
        "valid": validation["valid"] and bool(single_item_eligible),
        "errors": errors,
        "estimated_redemptions": validation["estimated_redemptions"],
        "estimated_coupon_cost": validation["estimated_coupon_cost"],
        "coupon_budget": coupon_budget,
        "campaign_budget": campaign_budget,
        "effective_budget_limit": effective_budget,
        "single_item_product_validations": product_validations,
        "single_item_eligible_product_ids": single_item_eligible,
        "cart_eligibility_requires_order_total": True,
    }


def build_campaign_context(
    campaign_request: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    products: Sequence[Mapping[str, Any]],
    coupons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply deterministic audience, recommendation, and coupon rules."""
    goal, budget, target_segment, coupon_id, redemption_rate = (
        _validate_campaign_request(campaign_request)
    )
    _validate_records(members, "会员")
    _validate_records(products, "商品")
    _validate_records(coupons, "优惠券")

    segment_results = []
    source_members = {}
    for member in members:
        _require_fields(
            member,
            (
                "member_id",
                "days_since_last_order",
                "order_count",
                "consent_marketing",
            ),
            "会员",
        )
        member_id = member["member_id"]
        if member_id in source_members:
            raise ValueError(f"会员编号重复: {member_id}")
        source_members[member_id] = member
        segment_results.append({
            **segment_member(member),
            "preferred_category": member.get("preferred_category", ""),
        })

    seen_product_ids = set()
    for product in products:
        _require_fields(
            product,
            ("product_id", "product_name", "category", "price", "cost", "stock"),
            "商品",
        )
        if product["product_id"] in seen_product_ids:
            raise ValueError(f"商品编号重复: {product['product_id']}")
        seen_product_ids.add(product["product_id"])

    seen_coupon_ids = set()
    for coupon in coupons:
        _require_fields(
            coupon,
            ("coupon_id", "coupon_name", "min_spend", "discount", "budget", "valid_days"),
            "优惠券",
        )
        if coupon["coupon_id"] in seen_coupon_ids:
            raise ValueError(f"优惠券编号重复: {coupon['coupon_id']}")
        seen_coupon_ids.add(coupon["coupon_id"])

    segments = Counter(item["segment"] for item in segment_results)
    audience = [
        item for item in segment_results
        if item["eligible_for_marketing"]
        and (target_segment is None or item["segment"] == target_segment)
    ]

    recommendations = []
    recommended_products = {}
    for member in audience:
        member_products = recommend_products(
            source_members[member["member_id"]],
            products,
        )
        recommended_products[member["member_id"]] = member_products
        recommendations.append({
            "member_id": member["member_id"],
            "segment": member["segment"],
            "products": member_products,
        })

    candidate_product_ids = {
        product["product_id"]
        for member_products in recommended_products.values()
        for product in member_products
    }
    candidate_products = [
        product for product in products
        if product["product_id"] in candidate_product_ids
    ]

    if coupon_id is None:
        selected_coupons = list(coupons)
    else:
        selected_coupons = [
            coupon for coupon in coupons if coupon.get("coupon_id") == coupon_id
        ]

    coupon_options = [
        _evaluate_coupon(
            coupon,
            candidate_products,
            audience_size=len(audience),
            campaign_budget=budget,
            redemption_rate=redemption_rate,
        )
        for coupon in selected_coupons
    ]
    if coupon_id is not None and not coupon_options:
        coupon_options = [{
            "coupon_id": coupon_id,
            "coupon_name": None,
            "valid": False,
            "errors": ["未找到指定优惠券"],
            "estimated_redemptions": 0,
            "estimated_coupon_cost": 0,
            "coupon_budget": None,
            "campaign_budget": budget,
            "effective_budget_limit": None,
            "single_item_product_validations": [],
            "single_item_eligible_product_ids": [],
            "cart_eligibility_requires_order_total": True,
        }]
    elif not coupon_options:
        coupon_options = [{
            "coupon_id": None,
            "coupon_name": None,
            "valid": False,
            "errors": ["未提供可校验的优惠券"],
            "estimated_redemptions": 0,
            "estimated_coupon_cost": 0,
            "coupon_budget": None,
            "campaign_budget": budget,
            "effective_budget_limit": None,
            "single_item_product_validations": [],
            "single_item_eligible_product_ids": [],
            "cart_eligibility_requires_order_total": True,
        }]

    return {
        "campaign": {
            "goal": goal,
            "budget": budget,
            "target_segment": target_segment,
            "coupon_id": coupon_id,
            "expected_redemption_rate": redemption_rate,
        },
        "audience": {
            "eligible_member_count": len(audience),
            "segment_counts": dict(segments),
            "members": audience,
        },
        "recommendations": recommendations,
        "coupon_options": coupon_options,
    }