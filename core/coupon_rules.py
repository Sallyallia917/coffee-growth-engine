def validate_campaign(
    coupon: dict,
    audience_size: int,
    expected_redemption_rate: float = 0.3,
    product: dict | None = None,
) -> dict:
    """校验活动规模、优惠券预算和单品折后毛利。"""
    errors = []

    min_spend = float(coupon["min_spend"])
    discount = float(coupon["discount"])
    budget = float(coupon["budget"])
    valid_days = int(coupon["valid_days"])

    if audience_size <= 0:
        errors.append("目标会员人数必须大于 0")

    if not 0 <= expected_redemption_rate <= 1:
        errors.append("预计核销率必须在 0 到 1 之间")

    if min_spend <= 0:
        errors.append("优惠门槛必须大于 0")

    if discount <= 0 or discount >= min_spend:
        errors.append("优惠金额必须大于 0 且小于优惠门槛")

    if budget < 0:
        errors.append("预算不能为负数")

    if valid_days <= 0:
        errors.append("优惠券有效期必须大于 0 天")

    estimated_redemptions = (
        audience_size * expected_redemption_rate
    )
    estimated_cost = estimated_redemptions * discount

    if estimated_cost > budget:
        errors.append(
            f"预计优惠成本 {estimated_cost:.2f} 超过预算 {budget:.2f}"
        )

    if product is not None:
        price = float(product["price"])
        cost = float(product["cost"])

        if price <= 0 or cost < 0 or cost > price:
            errors.append("商品价格或成本数据不合法")
        elif price - discount - cost < 0:
            errors.append("按该优惠金额计算，单品折后毛利为负")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "estimated_redemptions": round(estimated_redemptions, 2),
        "estimated_coupon_cost": round(estimated_cost, 2),
        "budget": budget,
    }