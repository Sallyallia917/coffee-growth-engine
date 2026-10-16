import json
from unittest.mock import Mock

import pytest
import requests

from services import llm_service
from services.llm_service import (
    LLMAPIError,
    LLMConfigurationError,
    LLMResponseError,
    generate_marketing_plan,
)


def business_context():
    return {
        "campaign": {
            "goal": "提升复购",
            "budget": 500,
            "target_segment": "活跃会员",
            "coupon_id": None,
            "expected_redemption_rate": 0.3,
        },
        "audience": {
            "eligible_member_count": 2,
            "segment_counts": {"活跃会员": 2},
            "members": [
                {"member_id": "PRIVATE-MEMBER", "segment": "活跃会员"}
            ],
        },
        "recommendations": [
            {
                "member_id": "PRIVATE-MEMBER",
                "segment": "活跃会员",
                "products": [
                    {
                        "product_id": "P001",
                        "product_name": "精品挂耳10包装",
                        "category": "挂耳咖啡",
                        "price": 59,
                        "cost": 25,
                        "stock": 50,
                    }
                ],
            }
        ],
        "coupon_options": [
            {
                "coupon_id": "C001",
                "coupon_name": "满50减5",
                "valid": True,
                "errors": [],
                "estimated_coupon_cost": 3,
                "effective_budget_limit": 100,
                "single_item_eligible_product_ids": ["P001"],
            },
            {
                "coupon_id": "C002",
                "coupon_name": "满200减25",
                "valid": False,
                "errors": ["没有推荐商品达到优惠门槛"],
                "estimated_coupon_cost": 15,
                "effective_budget_limit": 100,
                "single_item_eligible_product_ids": [],
            },
        ],
    }


def valid_plan(**overrides):
    plan = {
        "campaign_title": "为日常咖啡时光加一点新意",
        "strategy": "围绕挂耳咖啡推荐，邀请会员尝试便捷冲泡。",
        "copywriting": "选一杯喜欢的风味，开启轻松咖啡时光。",
        "channels": [
            {
                "channel": "短信",
                "message": "用一杯香醇咖啡，为今天留一点从容。",
            }
        ],
        "recommended_product_ids": ["P001"],
        "selected_coupon_ids": ["C001"],
        "compliance_notes": ["优惠资格以业务校验结果为准。"],
    }
    plan.update(overrides)
    return plan


class FakeResponse:
    def __init__(self, content=None, status_code=200, payload=None):
        self.ok = status_code < 400
        self.status_code = status_code
        self.content = content
        self.payload = payload

    def json(self):
        if self.payload is not None:
            return self.payload
        return {
            "choices": [
                {"message": {"content": json.dumps(self.content, ensure_ascii=False)}}
            ]
        }


def test_posts_sanitized_context_and_returns_structured_plan(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(content=valid_plan())

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    result = generate_marketing_plan(
        business_context(),
        api_key="test-secret",
    )

    assert result == valid_plan()
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    assert captured["timeout"] == 30
    user_message = captured["json"]["messages"][1]["content"]
    assert "PRIVATE-MEMBER" not in user_message
    assert "member_id" not in user_message
    assert captured["json"]["response_format"] == {"type": "json_object"}
    model_payload = json.loads(user_message)["business_context"]
    assert [coupon["coupon_id"] for coupon in model_payload["coupon_options"]] == [
        "C001"
    ]
    assert "C002" not in user_message


def test_requires_api_key_without_making_request(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    post = Mock(side_effect=AssertionError("API should not be called"))
    monkeypatch.setattr(
        llm_service.requests,
        "post",
        post,
    )

    with pytest.raises(LLMConfigurationError, match="DEEPSEEK_API_KEY"):
        generate_marketing_plan(business_context())
    post.assert_not_called()


def test_explains_that_business_context_must_come_from_campaign_service():
    with pytest.raises(ValueError, match="build_campaign_context"):
        llm_service._build_model_context({})


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(status_code=503), "HTTP 状态码：503"),
        (
            FakeResponse(payload={"choices": []}),
            "缺少模型生成内容",
        ),
        (
            FakeResponse(payload={"choices": [{"message": {"content": ""}}]}),
            "空的模型响应",
        ),
        (
            FakeResponse(payload={"choices": [{"message": {"content": "not-json"}}]}),
            "不是有效的 JSON",
        ),
        (
            FakeResponse(content={"strategy": "漏字段"}),
            "字段不符合约定",
        ),
    ],
)
def test_rejects_api_and_malformed_responses(monkeypatch, response, message):
    monkeypatch.setattr(
        llm_service.requests,
        "post",
        Mock(return_value=response),
    )

    with pytest.raises((LLMAPIError, LLMResponseError), match=message):
        generate_marketing_plan(business_context(), api_key="test-secret")


def test_timeout_is_reported_without_exposing_credentials(monkeypatch):
    monkeypatch.setattr(
        llm_service.requests,
        "post",
        Mock(side_effect=requests.Timeout("request timed out")),
    )

    with pytest.raises(LLMAPIError, match="请求超时") as error:
        generate_marketing_plan(
            business_context(),
            api_key="do-not-print-this",
        )
    assert "do-not-print-this" not in str(error.value)


def test_rejects_unvalidated_coupon_unknown_product_and_unsupported_numbers(
    monkeypatch,
):
    plans = [
        valid_plan(selected_coupon_ids=["C002"]),
        valid_plan(recommended_product_ids=["P999"]),
        valid_plan(
            recommended_product_ids=[],
            selected_coupon_ids=["C001"],
        ),
        valid_plan(copywriting="只需 99 元，即可享受优惠。"),
    ]

    for plan in plans:
        monkeypatch.setattr(
            llm_service.requests,
            "post",
            Mock(return_value=FakeResponse(content=plan)),
        )
        with pytest.raises(LLMResponseError):
            generate_marketing_plan(business_context(), api_key="test-secret")


def test_allows_numbers_only_when_quoting_selected_product_and_coupon_names():
    plan = valid_plan(
        copywriting="推荐精品挂耳10包装，使用满50减5。",
    )

    assert llm_service._validate_plan(
        plan,
        llm_service._build_model_context(business_context()),
        business_context(),
    ) == plan


def test_reports_unsupported_number_and_output_field():
    plan = valid_plan(copywriting="只需 99 元，即可享受优惠。")

    with pytest.raises(LLMResponseError) as error:
        llm_service._validate_plan(
            plan,
            llm_service._build_model_context(business_context()),
            business_context(),
        )

    assert "copywriting" in str(error.value)
    assert "'99'" in str(error.value)


def test_rejects_text_that_mentions_an_invalid_coupon(monkeypatch):
    plan = valid_plan(
        copywriting="使用满200减25，享受特别优惠。",
        selected_coupon_ids=["C001"],
    )
    monkeypatch.setattr(
        llm_service.requests,
        "post",
        Mock(return_value=FakeResponse(content=plan)),
    )

    with pytest.raises(LLMResponseError, match="未通过校验的优惠券"):
        generate_marketing_plan(business_context(), api_key="test-secret")


def test_rejects_valid_coupon_name_when_coupon_is_not_selected(monkeypatch):
    plan = valid_plan(
        copywriting="使用满50减5，为咖啡时光增加一点风味。",
        selected_coupon_ids=[],
    )
    monkeypatch.setattr(
        llm_service.requests,
        "post",
        Mock(return_value=FakeResponse(content=plan)),
    )

    with pytest.raises(LLMResponseError, match="未纳入方案的优惠券"):
        generate_marketing_plan(business_context(), api_key="test-secret")


def test_rejects_coupon_id_when_coupon_is_not_selected(monkeypatch):
    plan = valid_plan(
        copywriting="活动可参考 C001。",
        selected_coupon_ids=[],
    )
    monkeypatch.setattr(
        llm_service.requests,
        "post",
        Mock(return_value=FakeResponse(content=plan)),
    )

    with pytest.raises(LLMResponseError, match="未纳入方案的优惠券"):
        generate_marketing_plan(business_context(), api_key="test-secret")


def test_allows_coupon_free_plan_when_no_coupon_is_valid(monkeypatch):
    context = business_context()
    for coupon in context["coupon_options"]:
        coupon["valid"] = False
    plan = valid_plan(
        copywriting="选一杯喜欢的风味，开启轻松咖啡时光。",
        selected_coupon_ids=[],
    )
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(content=plan)

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    assert generate_marketing_plan(context, api_key="test-secret") == plan
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    sent_context = json.loads(
        captured["json"]["messages"][1]["content"]
    )["business_context"]
    assert sent_context["coupon_options"] == []


def test_excludes_valid_coupon_that_does_not_apply_to_recommended_products(
    monkeypatch,
):
    context = business_context()
    context["coupon_options"][0]["single_item_eligible_product_ids"] = ["P999"]
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(content=valid_plan(selected_coupon_ids=[]))

    monkeypatch.setattr(llm_service.requests, "post", fake_post)
    result = generate_marketing_plan(context, api_key="test-secret")

    assert result["selected_coupon_ids"] == []
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    sent_context = json.loads(
        captured["json"]["messages"][1]["content"]
    )["business_context"]
    assert sent_context["coupon_options"] == []


def test_retries_once_and_returns_corrected_plan_for_numeric_claim(monkeypatch):
    invalid_plan = valid_plan(copywriting="只需 99 元，即可享受优惠。")
    corrected_plan = valid_plan(copywriting="选一杯喜欢的风味，开启轻松咖啡时光。")
    post = Mock(side_effect=[
        FakeResponse(content=invalid_plan),
        FakeResponse(content=corrected_plan),
    ])
    monkeypatch.setattr(llm_service.requests, "post", post)

    result = generate_marketing_plan(business_context(), api_key="test-secret")

    assert result == corrected_plan
    assert post.call_count == 2
    retry_messages = post.call_args_list[1].kwargs["json"]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "copywriting" in retry_messages[-1]["content"]
    assert "'99'" in retry_messages[-1]["content"]


def test_fails_after_one_numeric_claim_retry(monkeypatch):
    invalid_plan = valid_plan(copywriting="只需 99 元，即可享受优惠。")
    post = Mock(return_value=FakeResponse(content=invalid_plan))
    monkeypatch.setattr(llm_service.requests, "post", post)

    with pytest.raises(LLMResponseError, match="已重试一次"):
        generate_marketing_plan(business_context(), api_key="test-secret")

    assert post.call_count == 2
