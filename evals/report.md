# Coffee Growth Engine 离线评测报告

- 评测集：coffee-growth-engine-offline-eval-v1
- 生成时间（UTC）：2026-10-24T07:16:19.077252+00:00
- 模式：offline_fixture_no_live_llm
- 案例数：8
- 案例通过：8
- 案例失败：0
- 案例通过率：100.0%

| 案例 | 类别 | 预期规则结果 | 实际规则结果 | 案例判定 |
|---|---|---:|---:|---|
| EVAL-001 | normal | True | True | 通过 |
| EVAL-002 | audience_edge | False | False | 通过 |
| EVAL-003 | budget_boundary | False | False | 通过 |
| EVAL-004 | invalid_product | False | False | 通过 |
| EVAL-005 | invalid_coupon | False | False | 通过 |
| EVAL-006 | coupon_product_mismatch | False | False | 通过 |
| EVAL-007 | schema_failure | False | False | 通过 |
| EVAL-008 | api_failure | False | False | 通过 |

## 结果解释

本报告使用固定的合成业务上下文，验证评测器能否识别预设的通过/失败情形；它不是 DeepSeek 与模板基线的效果对比，也不代表真实业务准确率、转化率或 ROI。
