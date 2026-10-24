"""Run the fixed offline evaluation suite without making live model/API calls.

Usage:
    python -m evals.run_evaluation
    python -m evals.run_evaluation --json-out evals/results.json --markdown-out evals/report.md
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.evaluation import (
    evaluate_business_rules,
    evaluate_marketing_plan,
    evaluate_run,
    summarize_evaluations,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.jsonl"


def _fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    context = {
        "campaign": {
            "goal": "提升复购", "budget": 100, "target_segment": "活跃会员",
            "coupon_id": None, "expected_redemption_rate": 0.3,
        },
        "audience": {
            "eligible_member_count": 1, "segment_counts": {"活跃会员": 1},
            "members": [{"member_id": "M001", "segment": "活跃会员"}],
        },
        "recommendations": [{
            "member_id": "M001", "segment": "活跃会员",
            "products": [{"product_id": "P001", "product_name": "拼配咖啡豆"}],
        }],
        "coupon_options": [{
            "coupon_id": "C001", "coupon_name": "满100减10", "valid": True,
            "errors": [], "estimated_coupon_cost": 20, "effective_budget_limit": 100,
            "single_item_eligible_product_ids": ["P001"],
        }],
    }
    plan = {
        "campaign_title": "咖啡会员复购活动",
        "strategy": "向目标会员推荐适配商品",
        "copywriting": "选一杯喜欢的风味，开启轻松咖啡时光。",
        "channels": [{"channel": "微信", "message": "发现适合你的咖啡风味。"}],
        "recommended_product_ids": ["P001"],
        "selected_coupon_ids": ["C001"],
        "compliance_notes": ["优惠资格以业务校验结果为准。"],
    }
    return context, plan


def _evaluate(case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    context, plan = _fixture()
    evaluator = case["evaluator"]

    if evaluator == "business_and_plan":
        business = evaluate_business_rules(context)
        plan_result = evaluate_marketing_plan(plan, context)
        actual = business["passed"] and plan_result["passed"]
        details = {"business_rules": business, "marketing_plan": plan_result}
    elif evaluator == "audience_count_mismatch":
        context["audience"]["eligible_member_count"] = 2
        result = evaluate_business_rules(context)
        actual, details = result["passed"], result
    elif evaluator == "coupon_over_budget":
        context["coupon_options"][0]["estimated_coupon_cost"] = 120
        result = evaluate_business_rules(context)
        actual, details = result["passed"], result
    elif evaluator == "invalid_product":
        plan["recommended_product_ids"] = ["P999"]
        result = evaluate_marketing_plan(plan, context)
        actual, details = result["passed"], result
    elif evaluator == "invalid_coupon":
        context["coupon_options"][0]["valid"] = False
        plan["selected_coupon_ids"] = ["C001"]
        result = evaluate_marketing_plan(plan, context)
        actual, details = result["passed"], result
    elif evaluator == "coupon_product_mismatch":
        context["coupon_options"][0]["single_item_eligible_product_ids"] = ["P999"]
        result = evaluate_marketing_plan(plan, context)
        actual, details = result["passed"], result
    elif evaluator == "schema_failure":
        plan.pop("campaign_title")
        result = evaluate_marketing_plan(plan, context)
        actual, details = result["passed"], result
    elif evaluator == "api_failure":
        result = evaluate_run({
            "run_id": case["case_id"], "context": context,
            "error": "simulated API failure", "latency_ms": None,
        })
        actual, details = result["status"] == "passed", result
    else:
        raise ValueError(f"Unsupported evaluator: {evaluator}")

    return actual, details


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} 不是有效 JSON：{exc}") from exc
        required = {"case_id", "category", "description", "evaluator", "expected_pass"}
        missing = required - set(case)
        if missing:
            raise ValueError(f"{path}:{line_number} 缺少字段：{', '.join(sorted(missing))}")
        cases.append(case)
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("评测案例 case_id 必须唯一")
    return cases


def run_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for case in cases:
        actual, details = _evaluate(case)
        expected = case["expected_pass"]
        results.append({
            "case_id": case["case_id"],
            "category": case["category"],
            "description": case["description"],
            "expected_pass": expected,
            "actual_pass": actual,
            "case_passed": actual is expected,
            "details": details,
        })
    summary = summarize_evaluations([{"passed": item["case_passed"]} for item in results])
    return {
        "suite": "coffee-growth-engine-offline-eval-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "offline_fixture_no_live_llm",
        "summary": summary,
        "cases": results,
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Coffee Growth Engine 离线评测报告", "",
        f"- 评测集：{report['suite']}",
        f"- 生成时间（UTC）：{report['generated_at_utc']}",
        f"- 模式：{report['evaluation_mode']}",
        f"- 案例数：{summary['total_cases']}",
        f"- 案例通过：{summary['passed_cases']}",
        f"- 案例失败：{summary['failed_cases']}",
        f"- 案例通过率：{summary['pass_rate']:.1%}", "",
        "| 案例 | 类别 | 预期规则结果 | 实际规则结果 | 案例判定 |",
        "|---|---|---:|---:|---|",
    ]
    for item in report["cases"]:
        lines.append(
            f"| {item['case_id']} | {item['category']} | "
            f"{item['expected_pass']} | {item['actual_pass']} | "
            f"{'通过' if item['case_passed'] else '失败'} |"
        )
    lines += [
        "", "## 结果解释", "",
        "本报告使用固定的合成业务上下文，验证评测器能否识别预设的通过/失败情形；"
        "它不是 DeepSeek 与模板基线的效果对比，也不代表真实业务准确率、转化率或 ROI。", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline marketing evaluation cases.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--json-out", type=Path, default=ROOT / "evals" / "results.json")
    parser.add_argument("--markdown-out", type=Path, default=ROOT / "evals" / "report.md")
    args = parser.parse_args()

    report = run_suite(load_cases(args.cases))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    for case in report["cases"]:
        marker = "PASS" if case["case_passed"] else "FAIL"
        print(f"{marker} {case['case_id']} [{case['category']}] expected={case['expected_pass']} actual={case['actual_pass']}")
    print(f"JSON report: {args.json_out.relative_to(ROOT) if args.json_out.is_relative_to(ROOT) else args.json_out}")
    print(f"Markdown report: {args.markdown_out.relative_to(ROOT) if args.markdown_out.is_relative_to(ROOT) else args.markdown_out}")
    return 0 if report["summary"]["failed_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
