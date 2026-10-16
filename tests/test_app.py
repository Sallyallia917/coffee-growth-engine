import csv

import pytest

from app import load_campaign_data, prepare_campaign_context


def write_csv(path, fieldnames, row):
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


def campaign_data():
    return {
        "members.csv": [
            {
                "member_id": "M001",
                "preferred_category": "咖啡豆",
                "days_since_last_order": "10",
                "order_count": "3",
                "consent_marketing": "True",
            }
        ],
        "products.csv": [
            {
                "product_id": "P001",
                "product_name": "咖啡豆礼盒",
                "category": "咖啡豆",
                "price": "120",
                "cost": "50",
                "stock": "5",
            }
        ],
        "coupons.csv": [
            {
                "coupon_id": "C001",
                "coupon_name": "满100减10",
                "min_spend": "100",
                "discount": "10",
                "budget": "100",
                "valid_days": "7",
            },
            {
                "coupon_id": "C002",
                "coupon_name": "满200减25",
                "min_spend": "200",
                "discount": "25",
                "budget": "100",
                "valid_days": "7",
            },
        ],
    }


def test_loads_current_project_data():
    data = load_campaign_data()

    assert len(data["members.csv"]) == 50
    assert len(data["products.csv"]) == 10
    assert len(data["coupons.csv"]) == 3


def test_rejects_csv_missing_required_columns(tmp_path):
    write_csv(tmp_path / "members.csv", ["member_id"], {"member_id": "M001"})

    with pytest.raises(ValueError, match="members.csv 缺少字段"):
        load_campaign_data(str(tmp_path))


def test_prepares_campaign_context_for_automatic_coupon_strategy():
    context = prepare_campaign_context(
        {"goal": "提升复购", "budget": 100, "expected_redemption_rate": 0.3},
        campaign_data(),
        "自动筛选可用优惠券",
    )

    assert context["campaign"]["coupon_id"] is None
    assert {coupon["coupon_id"] for coupon in context["coupon_options"]} == {
        "C001",
        "C002",
    }


def test_prepares_campaign_context_for_a_specific_coupon():
    context = prepare_campaign_context(
        {"goal": "提升复购", "budget": 100, "expected_redemption_rate": 0.3},
        campaign_data(),
        "指定优惠券",
        "C001",
    )

    assert context["campaign"]["coupon_id"] == "C001"
    assert [coupon["coupon_id"] for coupon in context["coupon_options"]] == ["C001"]


def test_prepares_coupon_free_campaign():
    context = prepare_campaign_context(
        {"goal": "提升复购", "budget": 100, "expected_redemption_rate": 0.3},
        campaign_data(),
        "不使用优惠券",
    )

    assert context["coupon_options"][0]["coupon_id"] is None
    assert context["coupon_options"][0]["valid"] is False
    assert context["coupon_options"][0]["errors"] == ["未提供可校验的优惠券"]


def test_requires_coupon_selection_for_specific_coupon_strategy():
    with pytest.raises(ValueError, match="请选择要校验的优惠券"):
        prepare_campaign_context(
            {"goal": "提升复购", "budget": 100},
            campaign_data(),
            "指定优惠券",
        )
