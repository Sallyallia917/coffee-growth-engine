from pathlib import Path
import random
import pandas as pd

random.seed(42)
OUT = Path(__file__).resolve().parent
OUT.mkdir(exist_ok=True)

# 1. 会员
members = []
for i in range(1, 51):
    members.append({
        "member_id": f"M{i:03d}",
        "member_name": f"会员{i:03d}",
        "preferred_category": random.choice(
            ["意式咖啡", "手冲咖啡", "咖啡豆", "挂耳咖啡"]
        ),
        "days_since_last_order": random.randint(0, 120),
        "order_count": random.randint(0, 25),
        "total_spend": round(random.uniform(0, 2500), 2),
        "consent_marketing": random.choice([True, True, True, False]),
    })

members_df = pd.DataFrame(members)
members_df.to_csv(OUT / "members.csv", index=False)

# 2. 商品
products = [
    ("P001", "经典意式拼配豆", "咖啡豆", 98, 45, 30),
    ("P002", "埃塞俄比亚日晒", "咖啡豆", 128, 62, 18),
    ("P003", "哥伦比亚水洗", "咖啡豆", 118, 57, 25),
    ("P004", "精品挂耳10包装", "挂耳咖啡", 59, 25, 50),
    ("P005", "精品挂耳20包装", "挂耳咖啡", 99, 44, 35),
    ("P006", "手冲体验套装", "手冲咖啡", 168, 95, 12),
    ("P007", "V60滤杯", "手冲咖啡", 88, 42, 20),
    ("P008", "浓缩咖啡液", "意式咖啡", 69, 30, 40),
    ("P009", "冷萃咖啡液", "意式咖啡", 79, 36, 0),
    ("P010", "入门咖啡礼盒", "礼盒", 198, 112, 8),
]

products_df = pd.DataFrame(
    products,
    columns=[
        "product_id", "product_name", "category",
        "price", "cost", "stock"
    ],
)
products_df.to_csv(OUT / "products.csv", index=False)

# 3. 订单：订单时间由距最近购买天数生成
orders = []
for member in members:
    for j in range(member["order_count"]):
        days_ago = (
            member["days_since_last_order"]
            if j == 0
            else random.randint(
                member["days_since_last_order"] + 1, 365
            )
        )
        product = random.choice(products)
        qty = random.randint(1, 3)
        orders.append({
            "order_id": f"O{len(orders) + 1:04d}",
            "member_id": member["member_id"],
            "product_id": product[0],
            "order_days_ago": days_ago,
            "quantity": qty,
            "amount": round(product[3] * qty, 2),
        })

orders_df = pd.DataFrame(
    orders,
    columns=[
        "order_id", "member_id", "product_id",
        "order_days_ago", "quantity", "amount"
    ],
)
orders_df.to_csv(OUT / "orders.csv", index=False)

# 4. 优惠券：折扣金额和预算均为模拟规则
coupons_df = pd.DataFrame([
    {
        "coupon_id": "C001", "coupon_name": "满100减10",
        "min_spend": 100, "discount": 10,
        "budget": 300, "valid_days": 7,
    },
    {
        "coupon_id": "C002", "coupon_name": "满200减25",
        "min_spend": 200, "discount": 25,
        "budget": 500, "valid_days": 7,
    },
    {
        "coupon_id": "C003", "coupon_name": "满50减5",
        "min_spend": 50, "discount": 5,
        "budget": 150, "valid_days": 3,
    },
])
coupons_df.to_csv(OUT / "coupons.csv", index=False)

# 5. 数据基本校验
assert (products_df["price"] > 0).all()
assert (products_df["cost"] >= 0).all()
assert (products_df["stock"] >= 0).all()
assert set(orders_df["member_id"]).issubset(
    set(members_df["member_id"])
)
assert set(orders_df["product_id"]).issubset(
    set(products_df["product_id"])
)

print(f"模拟数据生成完成：{OUT}")
print(f"会员：{len(members_df)}")
print(f"商品：{len(products_df)}")
print(f"订单：{len(orders_df)}")
print(f"优惠券：{len(coupons_df)}")