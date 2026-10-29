"""Run C01, C09 and C13 with a deterministic A baseline and DeepSeek B.

Outputs are written to a timestamped run directory. Existing evaluation files
are not modified. The blind key is stored separately from blind scoring packets.
"""
from __future__ import annotations

import csv
import json
import os
import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from services.campaign_service import build_campaign_context
from services.evaluation import evaluate_marketing_plan
from services.llm_service import generate_marketing_plan

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT_ROOT = ROOT / "evals" / "quality_v1" / "runs"
REQUIRED_PLAN_FIELDS = {
    "campaign_title", "strategy", "copywriting", "channels",
    "recommended_product_ids", "selected_coupon_ids", "compliance_notes",
}


def load_csv(filename: str) -> list[dict[str, str]]:
    path = DATA / filename
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"数据文件为空或不存在：{path}")
    return rows


def load_data() -> dict[str, list[dict[str, str]]]:
    return {
        "members": load_csv("members.csv"),
        "products": load_csv("products.csv"),
        "coupons": load_csv("coupons.csv"),
    }


def make_cases(data: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    # Pilot scenarios are explicit and reproducible.
    # C13 intentionally specifies C002: min spend 200, while current catalog
    # product prices top out below 200, so the coupon should not be promoted.
    specs = [
        {
            "case_id": "C01",
            "description": "常规场景：面向活跃会员的复购营销",
            "request": {
                "goal": "提升活跃会员复购，推荐适合其偏好且有库存的咖啡商品",
                "budget": 1000,
                "target_segment": "活跃会员",
                "expected_redemption_rate": 0.3,
            },
            "coupon_ids": None,
            "channel_constraint": None,
        },
        {
            "case_id": "C09",
            "description": "渠道约束：短信文案简短、明确、适合直接发送",
            "request": {
                "goal": "提升活跃会员复购；短信渠道文案必须简短，建议不超过70个汉字，突出一个明确行动",
                "budget": 1000,
                "target_segment": "活跃会员",
                "expected_redemption_rate": 0.3,
            },
            "coupon_ids": None,
            "channel_constraint": "SMS ≤ 70 Chinese characters (best-effort scoring constraint)",
        },
        {
            "case_id": "C13",
            "description": "优惠券边界：指定高门槛优惠券不适用时，不得宣传该券",
            "request": {
                "goal": "提升活跃会员复购；如果指定优惠券未通过校验，不得宣传该优惠券或虚构优惠，可推荐合适商品",
                "budget": 1000,
                "target_segment": "活跃会员",
                "coupon_id": "C002",
                "expected_redemption_rate": 0.3,
            },
            "coupon_ids": ["C002"],
            "channel_constraint": None,
        },
    ]

    cases = []
    for spec in specs:
        context = build_campaign_context(
            campaign_request=spec["request"],
            members=data["members"],
            products=data["products"],
            coupons=data["coupons"],
        )
        cases.append({**spec, "context": context})
    return cases


def aggregate_products(context: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for rec in context["recommendations"]:
        for product in rec["products"]:
            pid = product.get("product_id")
            if pid and pid not in seen:
                seen[pid] = product
    return list(seen.values())


def make_baseline(context: dict[str, Any], case_id: str) -> dict[str, Any]:
    """A transparent fixed-rule template baseline; not an intentionally weak arm."""
    products = aggregate_products(context)
    if not products:
        raise ValueError(f"{case_id}: 当前场景没有可推荐的商品，无法生成有效基线")

    valid_coupons = [
        c for c in context["coupon_options"]
        if c.get("valid") is True
        and c.get("single_item_eligible_product_ids")
    ]

    chosen_coupon = None
    chosen_product = products[0]
    for coupon in valid_coupons:
        eligible = set(coupon["single_item_eligible_product_ids"])
        matched = next((p for p in products if p["product_id"] in eligible), None)
        if matched:
            chosen_coupon, chosen_product = coupon, matched
            break

    selected_coupon_ids = [chosen_coupon["coupon_id"]] if chosen_coupon else []
    selected_product_ids = [chosen_product["product_id"]]

    product_name = chosen_product.get("product_name", "推荐咖啡商品")
    coupon_name = chosen_coupon.get("coupon_name") if chosen_coupon else None

    if coupon_name:
        title = f"{product_name}复购推荐"
        copy = f"最近想补充咖啡？可以看看{product_name}。符合使用条件时，可使用{coupon_name}。"
        sms = f"为你推荐{product_name}。符合使用条件时，可使用{coupon_name}，了解详情后再决定。"
        strategy = "依据目标会员分群与可推荐商品，选择一款商品；仅在优惠券通过校验且适用于该商品时才宣传。"
        compliance = ["仅使用通过业务校验的商品与优惠券", "优惠券实际使用条件以结算校验为准"]
    else:
        title = f"{product_name}复购推荐"
        copy = f"最近想补充咖啡？可以看看{product_name}，按自己的饮用习惯选择是否购买。"
        sms = f"为你推荐{product_name}，可查看商品详情，按需选购。"
        strategy = "依据目标会员分群与可推荐商品选择一款商品；当前没有适用且通过校验的优惠券，因此不宣传优惠。"
        compliance = ["未宣传未通过校验的优惠券", "不承诺未经验证的营销效果"]

    return {
        "campaign_title": title,
        "strategy": strategy,
        "copywriting": copy,
        "channels": [
            {"channel": "短信", "message": sms if case_id == "C09" else copy},
            {"channel": "会员触达", "message": copy},
        ],
        "recommended_product_ids": selected_product_ids,
        "selected_coupon_ids": selected_coupon_ids,
        "compliance_notes": compliance,
    }


def validate_shape(plan: Any) -> bool:
    if not isinstance(plan, dict) or set(plan) != REQUIRED_PLAN_FIELDS:
        return False
    if not all(isinstance(plan.get(k), str) and plan[k].strip()
               for k in ("campaign_title", "strategy", "copywriting")):
        return False
    if not all(isinstance(plan.get(k), list)
               for k in ("channels", "recommended_product_ids",
                         "selected_coupon_ids", "compliance_notes")):
        return False
    return all(
        isinstance(c, dict)
        and set(c) == {"channel", "message"}
        and isinstance(c["channel"], str)
        and isinstance(c["message"], str)
        for c in plan["channels"]
    )


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "未检测到 DEEPSEEK_API_KEY。请在 Codespaces Secrets 或本终端环境中配置；"
            "不要把密钥写进脚本、提交到 Git，或粘贴到聊天中。"
        )

    data = load_data()
    cases = make_cases(data)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    raw_records: list[dict[str, Any]] = []
    blind_packets: list[dict[str, Any]] = []
    blind_key: dict[str, dict[str, str]] = {}
    score_rows: list[dict[str, Any]] = []

    for case in cases:
        cid = case["case_id"]
        context = case["context"]

        for arm in ("A", "B"):
            started = time.perf_counter()
            plan = None
            error = None
            try:
                if arm == "A":
                    plan = make_baseline(context, cid)
                else:
                    plan = generate_marketing_plan(context)
            except Exception as exc:
                # Store the exception class and safe message; never store env vars.
                error = {"type": type(exc).__name__, "message": str(exc)[:800]}
            latency_ms = round((time.perf_counter() - started) * 1000, 1)

            evaluation = None
            if plan is not None:
                evaluation = evaluate_marketing_plan(plan, context)
                evaluation["shape_valid"] = validate_shape(plan)

            record = {
                "run_id": run_id,
                "case_id": cid,
                "case_description": case["description"],
                "arm": arm,
                "latency_ms": latency_ms,
                "status": "error" if error else (
                    "pass" if evaluation and evaluation.get("passed")
                    and evaluation.get("shape_valid") else "needs_review"
                ),
                "error": error,
                "context": context,
                "plan": plan,
                "evaluation": evaluation,
                "channel_constraint": case["channel_constraint"],
            }
            raw_records.append(jsonable(record))

            blind_id = "BL-" + uuid.uuid4().hex[:8].upper()
            blind_key[blind_id] = {"case_id": cid, "arm": arm}
            blind_packets.append({
                "blind_id": blind_id,
                "case_id": cid,
                "case_description": case["description"],
                "channel_constraint": case["channel_constraint"],
                "plan": plan,
                "error": error,
            })
            score_rows.append({
                "blind_id": blind_id,
                "case_id": cid,
                "business_relevance_1_5": "",
                "personalization_1_5": "",
                "channel_fit_1_5": "",
                "executability_1_5": "",
                "expression_quality_1_5": "",
                "hard_gate_fact_accuracy_pass": "",
                "hard_gate_compliance_pass": "",
                "notes": "",
            })
            print(f"{cid} / {arm}: {record['status']} | {latency_ms} ms")

    def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    random.SystemRandom().shuffle(blind_packets)
    random.SystemRandom().shuffle(score_rows)
    write_jsonl(out_dir / "raw_results.jsonl", raw_records)
    write_jsonl(out_dir / "blind_packets.jsonl", blind_packets)
    (out_dir / "blind_key.json").write_text(
        json.dumps(blind_key, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (out_dir / "blind_scores.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(score_rows[0].keys()))
        writer.writeheader()
        writer.writerows(score_rows)

    summary = {
        "run_id": run_id,
        "cases": [c["case_id"] for c in cases],
        "planned_outputs": len(cases) * 2,
        "actual_outputs": len(raw_records),
        "errors": sum(1 for r in raw_records if r["error"]),
        "structurally_valid_plans": sum(
            1 for r in raw_records
            if r["plan"] is not None and r["evaluation"]
            and r["evaluation"].get("shape_valid")
        ),
        "note": (
            "This is a three-case pilot using local sample data. "
            "It is not evidence of real-world conversion uplift."
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n试点评测完成。输出目录：")
    print(out_dir.relative_to(ROOT))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n评分时只打开 blind_packets.jsonl 和 blind_scores.csv。")
    print("blind_key.json 是揭盲映射，评分完成前请勿打开。")


if __name__ == "__main__":
    main()
