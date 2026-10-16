import csv
from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st

from services.campaign_service import build_campaign_context
from services.llm_service import LLMServiceError, generate_marketing_plan


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
REQUIRED_FIELDS = {
    "members.csv": {
        "member_id",
        "preferred_category",
        "days_since_last_order",
        "order_count",
        "consent_marketing",
    },
    "products.csv": {
        "product_id",
        "product_name",
        "category",
        "price",
        "cost",
        "stock",
    },
    "coupons.csv": {
        "coupon_id",
        "coupon_name",
        "min_spend",
        "discount",
        "budget",
        "valid_days",
    },
}
SEGMENTS = (
    "活跃会员",
    "复购召回",
    "沉睡待唤醒",
    "新会员待转化",
)


@st.cache_data
def load_campaign_data(data_dir: str = str(DATA_DIR)) -> dict[str, list[dict[str, str]]]:
    """Load and validate the CSV files used by the campaign rules."""
    root = Path(data_dir)
    records: dict[str, list[dict[str, str]]] = {}
    for filename, required_fields in REQUIRED_FIELDS.items():
        path = root / filename
        try:
            with path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                headers = set(reader.fieldnames or [])
                missing = required_fields - headers
                if missing:
                    raise ValueError(
                        f"{filename} 缺少字段：{', '.join(sorted(missing))}"
                    )
                rows = [
                    {key: value for key, value in row.items() if key is not None}
                    for row in reader
                    if any(value is not None and value.strip() for value in row.values())
                ]
        except OSError as exc:
            raise ValueError(f"无法读取数据文件 {path}: {exc}") from exc
        except csv.Error as exc:
            raise ValueError(f"数据文件 {filename} 格式错误: {exc}") from exc
        if not rows:
            raise ValueError(f"数据文件 {filename} 没有数据记录")
        records[filename] = rows
    return records


def prepare_campaign_context(
    campaign_request: dict[str, Any],
    data: dict[str, list[dict[str, str]]],
    coupon_strategy: str,
    coupon_id: str | None = None,
) -> dict[str, Any]:
    """Apply the selected coupon strategy and run deterministic business rules."""
    coupons = data["coupons.csv"]
    request = dict(campaign_request)
    if coupon_strategy == "自动筛选可用优惠券":
        request.pop("coupon_id", None)
    elif coupon_strategy == "指定优惠券":
        if not coupon_id:
            raise ValueError("请选择要校验的优惠券")
        request["coupon_id"] = coupon_id
    elif coupon_strategy == "不使用优惠券":
        request.pop("coupon_id", None)
        coupons = []
    else:
        raise ValueError("请选择有效的优惠券策略")

    return build_campaign_context(
        request,
        data["members.csv"],
        data["products.csv"],
        coupons,
    )


def _render_business_results(context: dict[str, Any]) -> None:
    st.subheader("业务规则结果")
    audience = context["audience"]
    st.metric("符合条件的可营销会员", audience["eligible_member_count"])
    st.caption("分群统计为完整会员数据集的分布（包含未授权营销的会员）。")
    st.dataframe(
        [
            {"会员分群": segment, "人数": count}
            for segment, count in audience["segment_counts"].items()
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("#### 目标会员")
    st.dataframe(
        [
            {
                "会员编号": member["member_id"],
                "分群": member["segment"],
                "偏好品类": member["preferred_category"],
            }
            for member in audience["members"]
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("#### 商品推荐")
    product_counts: Counter[str] = Counter()
    product_details: dict[str, dict[str, Any]] = {}
    for recommendation in context["recommendations"]:
        for product in recommendation["products"]:
            product_id = product["product_id"]
            product_counts[product_id] += 1
            product_details[product_id] = product
    st.dataframe(
        [
            {
                "商品编号": product_id,
                "商品名称": product_details[product_id]["product_name"],
                "品类": product_details[product_id]["category"],
                "价格": product_details[product_id]["price"],
                "库存": product_details[product_id]["stock"],
                "推荐会员数": count,
                "推荐理由": product_details[product_id]["reason"],
            }
            for product_id, count in product_counts.most_common()
        ],
        hide_index=True,
        use_container_width=True,
    )
    if not product_counts:
        st.info("当前目标会员没有可推荐的有库存商品。")

    st.markdown("#### 优惠券校验")
    st.dataframe(
        [
            {
                "优惠券": coupon.get("coupon_name") or coupon.get("coupon_id"),
                "编号": coupon.get("coupon_id"),
                "校验结果": "通过" if coupon["valid"] else "未通过",
                "预计优惠成本": coupon["estimated_coupon_cost"],
                "预算上限": coupon["effective_budget_limit"],
                "错误/限制": "；".join(coupon["errors"]) or "无",
                "单品可用商品": "、".join(
                    coupon["single_item_eligible_product_ids"]
                ) or "无",
            }
            for coupon in context["coupon_options"]
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_marketing_plan(plan: dict[str, Any]) -> None:
    st.subheader("AI 营销方案")
    st.markdown(f"### {plan['campaign_title']}")
    st.markdown(f"**策略：** {plan['strategy']}")
    st.markdown(f"**营销文案：** {plan['copywriting']}")
    st.markdown("#### 渠道文案")
    for channel in plan["channels"]:
        st.markdown(f"**{channel['channel']}**：{channel['message']}")
    st.markdown("#### 方案采用")
    st.write("推荐商品编号：", "、".join(plan["recommended_product_ids"]) or "无")
    st.write("优惠券编号：", "、".join(plan["selected_coupon_ids"]) or "不使用优惠券")
    if plan["compliance_notes"]:
        st.markdown("#### 合规说明")
        for note in plan["compliance_notes"]:
            st.write(f"- {note}")


def main() -> None:
    st.set_page_config(page_title="Coffee Growth Engine", page_icon="☕", layout="wide")
    st.title("☕ AI 咖啡营销方案")
    st.write("先由确定性业务规则完成人群、商品和优惠券校验，再生成营销方案。")

    try:
        data = load_campaign_data()
    except ValueError as exc:
        st.error(f"数据加载失败：{exc}")
        st.stop()

    coupon_names = {
        coupon["coupon_id"]: coupon["coupon_name"]
        for coupon in data["coupons.csv"]
    }

    with st.form("campaign_form"):
        goal = st.text_input("活动目标", value="提升复购")
        budget = st.number_input(
            "营销预算（元）",
            min_value=0.0,
            value=1000.0,
            step=100.0,
        )
        target_segment_choice = st.selectbox(
            "目标会员分群",
            ["所有已授权会员", *SEGMENTS],
        )
        redemption_rate = st.slider(
            "预计优惠券核销率",
            min_value=0.0,
            max_value=1.0,
            value=0.3,
            step=0.05,
            help="用于优惠券预算的确定性估算，不是模型预测。",
        )
        coupon_strategy = st.radio(
            "优惠策略",
            [
                "自动筛选可用优惠券",
                "指定优惠券",
                "不使用优惠券",
            ],
            horizontal=True,
        )
        selected_coupon_id = None
        if coupon_strategy == "指定优惠券":
            selected_coupon_id = st.selectbox(
                "选择优惠券",
                list(coupon_names),
                format_func=lambda coupon_id: (
                    f"{coupon_id} - {coupon_names[coupon_id]}"
                ),
            )
        generate_plan = st.checkbox("调用 DeepSeek 生成方案", value=True)
        submitted = st.form_submit_button(
            "计算业务结果并生成方案",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        request = {
            "goal": goal,
            "budget": budget,
            "expected_redemption_rate": redemption_rate,
        }
        if target_segment_choice != "所有已授权会员":
            request["target_segment"] = target_segment_choice
        try:
            context = prepare_campaign_context(
                request,
                data,
                coupon_strategy,
                selected_coupon_id,
            )
        except (TypeError, ValueError) as exc:
            st.error(f"输入或业务数据有误：{exc}")
            st.stop()

        st.session_state["campaign_context"] = context
        st.session_state.pop("marketing_plan", None)
        st.session_state.pop("llm_error", None)
        if generate_plan:
            with st.spinner("正在请求 DeepSeek 并校验方案……"):
                try:
                    st.session_state["marketing_plan"] = (
                        generate_marketing_plan(context)
                    )
                except (LLMServiceError, ValueError) as exc:
                    st.session_state["llm_error"] = str(exc)

    context = st.session_state.get("campaign_context")
    if context:
        _render_business_results(context)
        if "llm_error" in st.session_state:
            st.warning(
                "业务规则计算已完成，但 AI 方案未生成或未通过校验："
                f"{st.session_state['llm_error']}"
            )
            st.info("会员分群、商品推荐和优惠券校验结果仍可查看。")
        elif "marketing_plan" in st.session_state:
            _render_marketing_plan(st.session_state["marketing_plan"])
        else:
            st.info("当前仅显示业务规则结果；提交表单并勾选调用 DeepSeek 可生成方案。")


if __name__ == "__main__":
    main()