def recommend_products(member: dict, products, top_k: int = 3):
    """按会员偏好、毛利率和库存生成可解释的候选商品。"""
    preferred = member.get("preferred_category", "")

    candidates = []
    for product in products:
        price = float(product["price"])
        cost = float(product["cost"])
        stock = int(product["stock"])

        # 无库存、价格不合法或成本数据不合法的商品不推荐
        if stock <= 0 or price <= 0 or cost < 0 or cost > price:
            continue

        margin_rate = (price - cost) / price
        category_match = product["category"] == preferred

        # 规则评分：偏好匹配优先，其次考虑毛利率
        score = (2.0 if category_match else 0.0) + margin_rate

        candidates.append({
            **product,
            "score": round(score, 4),
            "reason": (
                "符合会员偏好"
                if category_match
                else "作为其他品类备选"
            ),
        })

    candidates.sort(
        key=lambda x: (x["score"], x["product_id"]),
        reverse=True,
    )
    return candidates[:top_k]