import pytest

from services.campaign_service import build_campaign_context


def member(**overrides):
    values = {
        "member_id": "M001",
        "days_since_last_order": 10,
        "order_count": 3,
        "preferred_category": "咖啡豆",
        "consent_marketing": True,
    }
    values.update(overrides)
    return values


def product(**overrides):
    values = {
        "product_id": "P001",
        "product_name": "拼配咖啡豆",
        "category": "咖啡豆",
        "price": 120,
        "cost": 50,
        "stock": 10,
    }
    values.update(overrides)
    return values


def coupon(**overrides):
    values = {
        "coupon_id": "C001",
        "coupon_name": "满100减10",
        "min_spend": 100,
        "discount": 10,
        "budget": 100,
        "valid_days": 7,
    }
    values.update(overrides)
    return values


def request(**overrides):
    values = {"goal": "提升复购", "budget": 100}
    values.update(overrides)
    return values


def test_builds_audience_recommendations_and_valid_coupon_context():
    result = build_campaign_context(
        request(),
        [member(), member(member_id="M002", consent_marketing=False)],
        [product()],
        [coupon()],
    )

    assert result["audience"]["eligible_member_count"] == 1
    assert [row["member_id"] for row in result["audience"]["members"]] == [
        "M001"
    ]
    assert result["recommendations"][0]["products"][0]["product_id"] == "P001"
    assert result["coupon_options"][0]["valid"] is True
    assert result["coupon_options"][0]["estimated_coupon_cost"] == 3


def test_filters_by_requested_segment_and_preserves_segment_counts():
    result = build_campaign_context(
        request(target_segment="沉睡待唤醒"),
        [member(), member(member_id="M002", days_since_last_order=70)],
        [product()],
        [],
    )

    assert result["audience"]["segment_counts"] == {
        "活跃会员": 1,
        "沉睡待唤醒": 1,
    }
    assert [row["member_id"] for row in result["audience"]["members"]] == [
        "M002"
    ]
    assert result["recommendations"][0]["member_id"] == "M002"


def test_returns_no_coupon_result_for_empty_coupon_data():
    result = build_campaign_context(
        request(),
        [member()],
        [product()],
        [],
    )

    assert result["coupon_options"][0]["valid"] is False
    assert result["coupon_options"][0]["errors"] == ["未提供可校验的优惠券"]


def test_empty_audience_and_products_are_reported_without_crashing():
    result = build_campaign_context(
        request(),
        [member(consent_marketing=False)],
        [],
        [coupon()],
    )

    assert result["audience"]["eligible_member_count"] == 0
    assert result["recommendations"] == []
    assert result["coupon_options"][0]["valid"] is False
    assert any(
        "目标会员人数必须大于 0" in error
        for error in result["coupon_options"][0]["errors"]
    )
    assert any(
        "没有推荐商品" in error
        for error in result["coupon_options"][0]["errors"]
    )


def test_rejects_missing_member_fields_and_duplicate_member_ids():
    with pytest.raises(ValueError, match="缺少必需字段"):
        build_campaign_context(
            request(),
            [{"member_id": "M001"}],
            [product()],
            [coupon()],
        )

    with pytest.raises(ValueError, match="会员编号重复"):
        build_campaign_context(
            request(),
            [member(), member()],
            [product()],
            [coupon()],
        )

    with pytest.raises(ValueError, match="商品缺少必需字段"):
        build_campaign_context(
            request(),
            [member()],
            [{"product_id": "P001"}],
            [coupon()],
        )


def test_reports_unknown_coupon_and_campaign_budget_overrun():
    unknown = build_campaign_context(
        request(coupon_id="C999"),
        [member()],
        [product()],
        [coupon()],
    )
    assert unknown["coupon_options"][0]["valid"] is False
    assert "未找到指定优惠券" in unknown["coupon_options"][0]["errors"]

    over_budget = build_campaign_context(
        request(budget=2),
        [member()],
        [product()],
        [coupon()],
    )
    assert over_budget["coupon_options"][0]["valid"] is False
    assert any(
        "超过预算" in error
        for error in over_budget["coupon_options"][0]["errors"]
    )


def test_coupon_needs_a_single_recommended_item_to_meet_threshold_and_margin():
    result = build_campaign_context(
        request(),
        [member()],
        [product(price=80), product(product_id="P002", price=120, cost=115)],
        [coupon()],
    )

    validation = result["coupon_options"][0]
    assert validation["valid"] is False
    assert validation["single_item_eligible_product_ids"] == []
