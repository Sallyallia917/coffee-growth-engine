from core.segmentation import segment_member
from core.recommendation import recommend_products
from core.coupon_rules import validate_campaign


def make_member(**overrides):
    member = {
        "member_id": "M001",
        "days_since_last_order": 75,
        "order_count": 5,
        "preferred_category": "咖啡豆",
        "consent_marketing": True,
    }
    member.update(overrides)
    return member


def test_unconsented_member_is_not_marketable():
    result = segment_member(
        make_member(consent_marketing=False)
    )
    assert result["eligible_for_marketing"] is False
    assert result["segment"] == "不可营销"


def test_no_purchase_member_is_not_dormant():
    result = segment_member(
        make_member(order_count=0)
    )
    assert result["segment"] == "新会员待转化"


def test_dormant_member_is_identified():
    result = segment_member(make_member())
    assert result["segment"] == "沉睡待唤醒"


def test_recommendation_excludes_out_of_stock():
    member = make_member()
    products = [
        {
            "product_id": "P001",
            "product_name": "咖啡豆A",
            "category": "咖啡豆",
            "price": 100,
            "cost": 50,
            "stock": 5,
        },
        {
            "product_id": "P002",
            "product_name": "咖啡豆B",
            "category": "咖啡豆",
            "price": 100,
            "cost": 50,
            "stock": 0,
        },
    ]

    result = recommend_products(member, products)
    ids = [p["product_id"] for p in result]

    assert "P001" in ids
    assert "P002" not in ids


def test_recommendation_returns_at_most_three():
    member = make_member()
    products = [
        {
            "product_id": f"P{i:03d}",
            "product_name": f"商品{i}",
            "category": "咖啡豆",
            "price": 100,
            "cost": 50,
            "stock": 10,
        }
        for i in range(1, 7)
    ]

    assert len(recommend_products(member, products)) == 3


def test_coupon_within_budget():
    coupon = {
        "min_spend": 100,
        "discount": 10,
        "budget": 500,
        "valid_days": 7,
    }

    result = validate_campaign(
        coupon,
        audience_size=100,
        expected_redemption_rate=0.3,
    )

    assert result["valid"] is True
    assert result["estimated_coupon_cost"] == 300


def test_coupon_over_budget_is_blocked():
    coupon = {
        "min_spend": 100,
        "discount": 20,
        "budget": 100,
        "valid_days": 7,
    }

    result = validate_campaign(
        coupon,
        audience_size=100,
        expected_redemption_rate=0.3,
    )

    assert result["valid"] is False
    assert any("超过预算" in e for e in result["errors"])


def test_negative_margin_is_blocked():
    coupon = {
        "min_spend": 100,
        "discount": 60,
        "budget": 1000,
        "valid_days": 7,
    }
    product = {
        "price": 100,
        "cost": 50,
    }

    result = validate_campaign(
        coupon,
        audience_size=10,
        expected_redemption_rate=0.1,
        product=product,
    )

    assert result["valid"] is False
    assert any("毛利为负" in e for e in result["errors"])