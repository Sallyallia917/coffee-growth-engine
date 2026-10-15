def segment_member(member: dict) -> dict:
    """根据会员最近购买时间、订单次数和营销授权进行分群。"""
    days = int(member["days_since_last_order"])
    count = int(member["order_count"])
    consent = str(member["consent_marketing"]).lower() == "true"

    if not consent:
        segment = "不可营销"
        reason = "会员未授权营销"
    elif count == 0:
        segment = "新会员待转化"
        reason = "暂无购买记录"
    elif days >= 60:
        segment = "沉睡待唤醒"
        reason = f"距上次购买已 {days} 天"
    elif days >= 30:
        segment = "复购召回"
        reason = f"距上次购买已 {days} 天"
    else:
        segment = "活跃会员"
        reason = f"距上次购买 {days} 天"

    return {
        "member_id": member["member_id"],
        "segment": segment,
        "reason": reason,
        "eligible_for_marketing": consent,
    }


def segment_members(members):
    return [segment_member(m) for m in members]