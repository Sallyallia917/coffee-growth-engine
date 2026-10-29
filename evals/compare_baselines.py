import json
import time
from services.llm_service import generate_marketing_plan
from services.evaluation import evaluate_marketing_plan

context = {
    "campaign": {
        "goal": "提升复购",
        "budget": 100,
        "target_segment": "活跃会员",
        "coupon_id": None,
        "expected_redemption_rate": 0.3,
    },
    "audience": {
        "eligible_member_count": 1,
        "segment_counts": {"活跃会员": 1},
        "members": [{"member_id": "M001", "segment": "活跃会员"}],
    },
    "recommendations": [
        {
            "member_id": "M001",
            "segment": "活跃会员",
            "products": [
                {"product_id": "P001", "product_name": "拼配咖啡豆"}
            ],
        }
    ],
    "coupon_options": [
        {
            "coupon_id": "C001",
            "coupon_name": "满100减10",
            "valid": True,
            "errors": [],
            "estimated_coupon_cost": 20,
            "effective_budget_limit": 100,
            "single_item_eligible_product_ids": ["P001"],
        }
    ],
}

template_plan = {
    "campaign_title": "活跃会员复购专享",
    "strategy": "向活跃会员推荐拼配咖啡豆，搭配已校验的优惠券。",
    "copywriting": "感谢您的支持！选购拼配咖啡豆，可使用满100减10优惠券。",
    "channels": [
        {
            "channel": "站内信",
            "message": "活跃会员专享：拼配咖啡豆推荐给您，欢迎再次选购。",
        }
    ],
    "recommended_product_ids": ["P001"],
    "selected_coupon_ids": ["C001"],
    "compliance_notes": ["商品和优惠券均来自已校验的业务数据。"],
}


def run_case(name, generator):
    started = time.perf_counter()
    try:
        plan = generator()
        latency = round(time.perf_counter() - started, 3)
        evaluation = evaluate_marketing_plan(plan, context)
        result = {
            "baseline": name,
            "latency_seconds": latency,
            "evaluation": evaluation,
            "plan": plan,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return result
    except Exception as exc:
        result = {
            "baseline": name,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result


if __name__ == "__main__":
    print("=== A: 固定模板 ===")
    a = run_case("template", lambda: template_plan)

    print("\n=== B: DeepSeek ===")
    b = run_case(
        "deepseek",
        lambda: generate_marketing_plan(context),
    )

    report = {
        "context": {
            "goal": context["campaign"]["goal"],
            "budget": context["campaign"]["budget"],
            "target_segment": context["campaign"]["target_segment"],
        },
        "results": [a, b],
        "limitations": [
            "仅使用一份合成业务上下文，不能代表整体效果。",
            "规则评测通过不等于营销文案质量更高。",
            "未测量真实转化率、复购率或ROI。",
            "单次响应耗时不代表稳定性能。",
        ],
    }

    with open("evals/baseline_comparison.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print("\n对比结果已保存：evals/baseline_comparison.json")
