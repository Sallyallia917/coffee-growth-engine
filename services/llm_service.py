import json
import os
import re
from collections.abc import Mapping
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from prompts.marketing_prompt import build_messages

load_dotenv()

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_TOKENS = 1200
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")


class LLMServiceError(RuntimeError):
    """Base class for user-safe LLM service errors."""


class LLMConfigurationError(LLMServiceError):
    """The service is not configured with the required credentials."""


class LLMAPIError(LLMServiceError):
    """The remote service failed or could not be reached."""


class LLMResponseError(LLMServiceError):
    """The remote service returned an empty or invalid response."""


class _UnsupportedNumericClaim(LLMResponseError):
    """Generated text contains a number unsupported by selected business data."""


def _build_model_context(context: Mapping[str, Any]) -> dict[str, Any]:
    required = ("campaign", "audience", "recommendations", "coupon_options")
    missing = [key for key in required if key not in context]
    if missing:
        raise ValueError(
            "传入的不是 campaign_service.build_campaign_context(...) "
            f"返回值；业务上下文缺少必需字段: {', '.join(missing)}"
        )

    campaign = context["campaign"]
    audience = context["audience"]
    recommendations = context["recommendations"]
    coupon_options = context["coupon_options"]
    if not isinstance(campaign, Mapping) or not isinstance(audience, Mapping):
        raise ValueError("业务活动和受众数据必须是对象")
    if not isinstance(recommendations, list) or not isinstance(coupon_options, list):
        raise ValueError("推荐结果和优惠券校验结果必须是列表")

    products: dict[str, dict[str, Any]] = {}
    for recommendation in recommendations:
        if not isinstance(recommendation, Mapping):
            raise ValueError("商品推荐记录必须是对象")
        member_products = recommendation.get("products")
        if not isinstance(member_products, list):
            raise ValueError("会员推荐商品必须是列表")
        for product in member_products:
            if not isinstance(product, Mapping):
                raise ValueError("推荐商品必须是对象")
            product_id = product.get("product_id")
            if not isinstance(product_id, str) or not product_id:
                raise ValueError("推荐商品缺少有效的 product_id")
            products[product_id] = {
                key: product[key]
                for key in ("product_id", "product_name", "category", "price", "stock")
                if key in product
            }

    coupons = []
    for coupon in coupon_options:
        if not isinstance(coupon, Mapping):
            raise ValueError("优惠券校验记录必须是对象")
        eligible_product_ids = coupon.get(
            "single_item_eligible_product_ids", []
        )
        if not isinstance(eligible_product_ids, list):
            raise ValueError("优惠券适用商品编号必须是列表")
        applicable_product_ids = [
            product_id
            for product_id in eligible_product_ids
            if product_id in products
        ]
        if coupon.get("valid") is not True or not applicable_product_ids:
            continue
        coupons.append({
            key: coupon[key]
            for key in (
                "coupon_id",
                "coupon_name",
                "valid",
                "errors",
                "estimated_coupon_cost",
                "effective_budget_limit",
            )
            if key in coupon
        } | {
            "single_item_eligible_product_ids": applicable_product_ids,
        })

    return {
        "campaign": {
            key: campaign[key]
            for key in (
                "goal",
                "budget",
                "target_segment",
                "coupon_id",
                "expected_redemption_rate",
            )
            if key in campaign
        },
        "audience": {
            key: audience[key]
            for key in ("eligible_member_count", "segment_counts")
            if key in audience
        },
        "recommended_products": list(products.values()),
        "coupon_options": coupons,
    }


def _validate_plan(
    plan: Any,
    model_context: Mapping[str, Any],
    source_context: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise LLMResponseError("模型响应必须是 JSON 对象")

    required_fields = {
        "campaign_title",
        "strategy",
        "copywriting",
        "channels",
        "recommended_product_ids",
        "selected_coupon_ids",
        "compliance_notes",
    }
    if set(plan) != required_fields:
        raise LLMResponseError("模型响应字段不符合约定的输出结构")
    for field in ("campaign_title", "strategy", "copywriting"):
        if not isinstance(plan[field], str) or not plan[field].strip():
            raise LLMResponseError(f"模型响应字段 {field} 必须是非空字符串")
    for field in ("recommended_product_ids", "selected_coupon_ids", "compliance_notes"):
        if not isinstance(plan[field], list) or not all(
            isinstance(item, str) for item in plan[field]
        ):
            raise LLMResponseError(f"模型响应字段 {field} 必须是字符串列表")
    if not isinstance(plan["channels"], list) or not plan["channels"]:
        raise LLMResponseError("模型响应字段 channels 必须是非空列表")
    for channel in plan["channels"]:
        if (
            not isinstance(channel, dict)
            or set(channel) != {"channel", "message"}
            or not isinstance(channel["channel"], str)
            or not channel["channel"].strip()
            or not isinstance(channel["message"], str)
            or not channel["message"].strip()
        ):
            raise LLMResponseError("模型响应中的渠道格式无效")

    source_products = {
        product["product_id"]: product
        for product in model_context["recommended_products"]
    }
    invalid_products = set(plan["recommended_product_ids"]) - set(source_products)
    if invalid_products:
        raise LLMResponseError("模型选择了业务上下文中不存在的推荐商品")
    if len(set(plan["recommended_product_ids"])) != len(plan["recommended_product_ids"]):
        raise LLMResponseError("模型响应包含重复的推荐商品")

    coupons = {
        coupon.get("coupon_id"): coupon
        for coupon in model_context["coupon_options"]
        if isinstance(coupon.get("coupon_id"), str)
    }
    selected_coupons = plan["selected_coupon_ids"]
    if len(set(selected_coupons)) != len(selected_coupons):
        raise LLMResponseError("模型响应包含重复的优惠券")
    for coupon_id in selected_coupons:
        coupon = coupons.get(coupon_id)
        if coupon is None or coupon.get("valid") is not True:
            raise LLMResponseError("模型选择了未通过业务校验的优惠券")
        eligible_ids = coupon.get("single_item_eligible_product_ids", [])
        if not set(eligible_ids).intersection(plan["recommended_product_ids"]):
            raise LLMResponseError("所选优惠券不适用于方案中的推荐商品")

    text_fields = [
        ("campaign_title", plan["campaign_title"]),
        ("strategy", plan["strategy"]),
        ("copywriting", plan["copywriting"]),
    ]
    for index, channel in enumerate(plan["channels"]):
        text_fields.extend([
            (f"channels[{index}].channel", channel["channel"]),
            (f"channels[{index}].message", channel["message"]),
        ])
    text_fields.extend(
        (f"compliance_notes[{index}]", note)
        for index, note in enumerate(plan["compliance_notes"])
    )
    output_text = "\n".join(value for _, value in text_fields)
    selected_product_ids = set(plan["recommended_product_ids"])
    for product_id, product in source_products.items():
        product_name = product.get("product_name")
        if (
            isinstance(product_name, str)
            and product_name
            and product_name in output_text
            and product_id not in selected_product_ids
        ):
            raise LLMResponseError("模型文案提及了未纳入方案的推荐商品")

    source_coupons = source_context["coupon_options"]
    for coupon in source_coupons:
        coupon_id = coupon.get("coupon_id")
        coupon_name = coupon.get("coupon_name")
        mentioned = (
            (isinstance(coupon_id, str) and coupon_id and coupon_id in output_text)
            or (
                isinstance(coupon_name, str)
                and coupon_name
                and coupon_name in output_text
            )
        )
        if mentioned and coupon.get("valid") is not True:
            raise LLMResponseError("模型文案提及了未通过校验的优惠券")
        if mentioned and coupon_id not in selected_coupons:
            raise LLMResponseError("模型文案提及了未纳入方案的优惠券")

    approved_names = [
        source_products[product_id].get("product_name")
        for product_id in selected_product_ids
    ]
    approved_names.extend(
        coupon.get("coupon_name")
        for coupon in source_coupons
        if coupon.get("coupon_id") in selected_coupons
        and coupon.get("valid") is True
    )
    approved_names = [
        name for name in approved_names if isinstance(name, str) and name
    ]
    for field, value in text_fields:
        approved_spans = []
        for name in approved_names:
            start = 0
            while (position := value.find(name, start)) != -1:
                approved_spans.append((position, position + len(name)))
                start = position + len(name)
        for match in _NUMBER_PATTERN.finditer(value):
            if not any(
                start <= match.start() and match.end() <= end
                for start, end in approved_spans
            ):
                raise _UnsupportedNumericClaim(
                    f"模型文案字段 {field} 包含未授权数字 {match.group(0)!r}；"
                    "只允许在原样引用本方案已选择的商品或优惠券名称时使用数字"
                )

    return plan


def _chat_completions_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMConfigurationError("DEEPSEEK_BASE_URL 必须是有效的 HTTP(S) 地址")
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def generate_marketing_plan(
    campaign_context: Mapping[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Generate and validate a marketing plan from deterministic business results."""
    key = api_key or os.getenv("DEEPSEEK_API_KEY")
    if not key or not key.strip():
        raise LLMConfigurationError(
            "未配置 DEEPSEEK_API_KEY；请在 .env 或环境变量中设置 DeepSeek API 密钥"
        )
    key = key.strip()
    endpoint = _chat_completions_url(
        base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    )
    selected_model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
    if not selected_model.strip():
        raise LLMConfigurationError("DEEPSEEK_MODEL 不能为空")
    selected_model = selected_model.strip()
    try:
        request_timeout = float(
            timeout
            if timeout is not None
            else os.getenv("DEEPSEEK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(
            "DEEPSEEK_TIMEOUT_SECONDS 必须是正数"
        ) from exc
    if not isfinite(request_timeout) or request_timeout <= 0:
        raise LLMConfigurationError("DEEPSEEK_TIMEOUT_SECONDS 必须是正数")

    model_context = _build_model_context(campaign_context)
    messages = build_messages(model_context)

    def get_model_response() -> Any:
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": selected_model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "max_tokens": MAX_RESPONSE_TOKENS,
                    "temperature": 0.7,
                },
                timeout=request_timeout,
            )
        except requests.Timeout as exc:
            raise LLMAPIError(
                f"DeepSeek 请求超时（{request_timeout:g} 秒）"
            ) from exc
        except requests.RequestException as exc:
            raise LLMAPIError(
                "无法连接 DeepSeek 服务，请检查网络和服务地址"
            ) from exc

        if not response.ok:
            raise LLMAPIError(
                f"DeepSeek API 请求失败，HTTP 状态码：{response.status_code}"
            )
        try:
            response_data = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise LLMResponseError("DeepSeek 返回了无效的 JSON 响应") from exc

        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("DeepSeek 响应缺少模型生成内容") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("DeepSeek 返回了空的模型响应")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("模型输出不是有效的 JSON 对象") from exc

    plan = get_model_response()
    try:
        return _validate_plan(plan, model_context, campaign_context)
    except _UnsupportedNumericClaim as first_error:
        messages.append({
            "role": "user",
            "content": (
                f"上一份方案未通过校验：{first_error}。"
                "请重新生成完整 JSON 方案；删除该字段中未授权的数字，"
                "只有原样引用本方案实际选择的商品或优惠券完整名称时才可保留数字。"
                "不要加入任何价格、数量、优惠金额、期限或比例等数字主张。"
            ),
        })
        retry_plan = get_model_response()
        try:
            return _validate_plan(retry_plan, model_context, campaign_context)
        except _UnsupportedNumericClaim as retry_error:
            raise LLMResponseError(
                f"{retry_error}；已重试一次，仍未通过校验"
            ) from retry_error