import json

from evals.run_evaluation import load_cases, run_suite


def test_fixed_eval_cases_are_executable_and_match_expectations():
    cases = load_cases()
    report = run_suite(cases)

    assert report["evaluation_mode"] == "offline_fixture_no_live_llm"
    assert report["summary"]["total_cases"] == len(cases)
    assert report["summary"]["failed_cases"] == 0
    assert report["summary"]["pass_rate"] == 1.0


def test_case_catalog_contains_unique_ids_and_supported_evaluators():
    cases = load_cases()
    assert len({case["case_id"] for case in cases}) == len(cases)
    supported = {
        "business_and_plan", "audience_count_mismatch", "coupon_over_budget",
        "invalid_product", "invalid_coupon", "coupon_product_mismatch",
        "schema_failure", "api_failure",
    }
    assert all(case["evaluator"] in supported for case in cases)


def test_report_can_be_serialized_to_json():
    report = run_suite(load_cases())
    serialized = json.dumps(report, ensure_ascii=False)
    assert "EVAL-001" in serialized
    assert "offline_fixture_no_live_llm" in serialized
