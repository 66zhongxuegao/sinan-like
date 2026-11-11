"""双层拦截网测试（离线，不调用模型）。"""

from tripcraft.services.guard_service import (CHECKERS, GuardService, check_contract,
                                              check_itinerary_text, check_quote,
                                              check_requirement, parse_quote)

GOOD_QUOTE = """3大1小，10月20日出发，5天
导游服务费 800 元
用车（7座商务含司机） 2400 元
酒店 4晚 1920 元
门票 600 元
餐饮 500 元
保险 60 元
合计 6280 元
成本 5600 元"""


def test_parse_quote_reads_items_and_summary():
    p = parse_quote(GOOD_QUOTE)
    assert len(p["items"]) == 6, "应解析出 6 条分项（含保险）"
    assert p["summary"] == 6280
    assert p["cost"] == 5600
    names = [i["name"] for i in p["items"]]
    assert any("用车" in n for n in names), "带括号与数字的项目名也要能解析"


def test_good_quote_passes_deterministic_layer():
    r = check_quote(GOOD_QUOTE)
    assert r["errors"] == [], r["errors"]


def test_quote_arithmetic_mismatch_is_blocking():
    r = check_quote("导游 800 元\n用车 2400 元\n酒店 1800 元\n合计 4200 元\n保险 60 元")
    assert any("不一致" in e for e in r["errors"])


def test_quote_negative_margin_is_blocking():
    r = check_quote("用车 3000 元\n酒店 3000 元\n合计 4200 元\n成本 5000 元\n保险 60 元")
    assert any("毛利" in e for e in r["errors"])


def test_quote_without_insurance_is_blocking():
    r = check_quote("导游 800 元\n用车 2400 元\n合计 3200 元")
    assert any("保险" in e for e in r["errors"])


def test_itinerary_requires_day_timeline():
    r = check_itinerary_text("昆明、大理、丽江一共五天。")
    assert any("逐日时间轴" in e for e in r["errors"])
    ok = check_itinerary_text("D1 抵达昆明，入住酒店；D2 石林，含午餐；D3 返程，含早餐。")
    assert ok["errors"] == []


def test_requirement_requires_four_categories():
    r = check_requirement("必须满足：3大1小；希望满足：节奏慢")
    assert any("可替代" in e and "明确不要" in e for e in r["errors"])
    ok = check_requirement("必须满足：3大1小、预算人均5000；希望满足：节奏慢；可替代：酒店降一档；明确不要：石林")
    assert ok["errors"] == []


def test_contract_requires_insurance_and_signing():
    assert check_contract("已生成合同，客户待签署。")["errors"]
    assert check_contract("合同已签署，保险已购买，定金已收。")["errors"] == []


def test_guard_check_combines_layers_without_llm():
    g = GuardService()
    out = g.check("分项报价", "导游 800 元\n合计 5000 元")
    assert out["blocked"] is True
    assert out["semantic"]["skipped"] is True, "未配置模型时应跳过语义层而不是报错"
    assert out["layers"] == ["deterministic", "semantic"]
    assert out["reasons"]


def test_guard_passes_good_deliverable_without_llm():
    g = GuardService()
    out = g.check("分项报价", GOOD_QUOTE)
    assert out["blocked"] is False
    assert out["verdict"] in ("pass", "warn")


def test_every_deliverable_kind_has_a_checker():
    for kind in ("分项报价", "行程方案", "需求确认单", "合同与保险"):
        assert kind in CHECKERS