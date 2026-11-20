from unittest.mock import patch

import pandas as pd

from utils import calculator


def basket(month, breadth=False):
    return pd.DataFrame({
        "투자월": month,
        "종목선정일": (pd.Period(month, freq="M") - 1).end_time.strftime("%Y-%m-%d"),
        "종목코드": [f"{code:05d}0" for code in range(200)],
        "시가총액": range(200, 0, -1),
        "1개월(%)": -1.0 if breadth else 1.0,
        "3개월(%)": -1.0 if breadth else 1.0,
        "6개월(%)": 1.0,
        "12개월(%)": 1.0,
        "이번달수익률": 1.0,
    })


def test_backtest_adds_inverse_to_direct_cash_defense_only():
    frames = [
        basket("2026-01", breadth=True), basket("2026-02"),
        basket("2026-03"), basket("2026-04"), basket("2026-05"),
    ]
    months = [frame["투자월"].iat[0] for frame in frames]
    settings = dict(use_gold=True, use_gold_ma=True, gold_returns=dict.fromkeys(months, 5.0))
    inverse_returns = dict.fromkeys(months, 8.0)
    with patch.object(calculator, "get_kospi_timing_for_backtest", return_value={"2026-03": True, "2026-04": True}), \
            patch.object(calculator, "get_gold_timing_for_backtest", return_value={m: m != "2026-04" for m in months}):
        args = (pd.concat(frames), 2026, 2026, 6, True, (1, 6), (1, 2), 30, 30)
        enabled, trades, details = calculator.run_backtest_k200(
            *args, **settings, use_inverse=True, inverse_returns=inverse_returns,
        )
        disabled, _, _ = calculator.run_backtest_k200(
            *args, **settings, use_inverse=False, inverse_returns=inverse_returns,
        )
        _, _, absent = calculator.run_backtest_k200(
            *args, **settings, use_inverse=True, inverse_returns={},
        )
    assert details["방어자산"].fillna("주식").tolist() == ["인버스", "현금", "인버스", "금", "주식"]
    assert enabled["invested"].tolist() == [False, False, False, False, True]
    assert enabled["앙상블 (50:50 전략)"].tolist() == [7.5, 0.0, 7.5, 4.5, 0.5]
    assert disabled["앙상블 (50:50 전략)"].tolist() == [0.0, 0.0, 0.0, 4.5, 0.5]
    assert trades[trades["전략"].eq("인버스 방어")]["투자월"].tolist() == ["2026-01", "2026-03"]
    assert absent["방어자산"].fillna("주식").tolist() == ["현금", "현금", "현금", "금", "주식"]
    assert "인버스 종가 없음" in absent["중지 사유"].iat[0]


def test_live_monthly_uses_same_gold_and_extension_rule():
    prev = basket("2026-01", breadth=True)
    current = basket("2026-02")
    gold = pd.DataFrame({"price": [100, 100, 100, 100, 100, 90, 200]},
                        index=pd.period_range("2025-08", "2026-02", freq="M").astype(str))
    with patch.object(calculator, "get_gold_krw_monthly", return_value=gold), \
            patch.object(calculator, "get_kospi_ma_all", return_value=(101, {6: 100})):
        extended = calculator.get_korea_market_status(current, prev)
        direct = calculator.get_korea_market_status(basket("2026-02", breadth=True), prev)
        gap = calculator.get_korea_market_status(current, basket("2025-12", breadth=True))
    assert (extended["reason"], extended["defense_alloc"]) == ("하락장 연장", "현금 100")
    assert (direct["reason"], direct["defense_alloc"]) == ("하락장", "인버스 100")
    assert not gap["stop"]


def test_backtest_extension_starts_with_previous_calendar_month():
    frames = [basket("2025-12", breadth=True), basket("2026-01"), basket("2026-02")]
    with patch.object(calculator, "get_kospi_timing_for_backtest", return_value={}), \
            patch.object(calculator, "get_gold_timing_for_backtest", return_value={"2026-01": True}):
        result, _, details = calculator.run_backtest_k200(
            pd.concat(frames), 2026, 2026, 6, True, (1, 6), (1, 2), 30, 30,
            use_gold=True, use_gold_ma=True, use_inverse=True, inverse_returns={"2026-01": 8.0},
        )
    assert result["invested"].tolist() == [False, True]
    assert details["방어자산"].iat[0] == "현금"
    assert result["중지 사유"].iat[0].startswith("하락장 연장")


def test_inverse_returns_require_adjacent_month_ends():
    closes = pd.Series([10.0, 11.0, 12.0, 13.0], index=pd.to_datetime([
        "2009-09-30", "2009-10-30", "2009-12-30", "2010-01-29",
    ]))
    market = pd.DataFrame(index=pd.to_datetime(["2010-01-29"]))
    with patch.object(calculator, "get_kospi_inverse_daily", return_value=closes), \
            patch.object(calculator, "_load_kospi_index", return_value=market):
        returns = calculator.get_kospi_inverse_returns()
    assert list(returns) == ["2009-10", "2010-01"]
    assert abs(returns["2009-10"] - 10.0) < 1e-10


def test_gold_defense_signal_available_before_new_months_first_quote():
    gold = pd.DataFrame({"price": [100, 100, 100, 100, 100, 90]},
                        index=pd.period_range("2025-08", "2026-01", freq="M").astype(str))
    with patch.object(calculator, "get_gold_krw_monthly", return_value=gold):
        result = calculator.get_gold_timing_for_backtest.__wrapped__(6, require_consecutive=True)
    assert result["2026-02"] is True


def test_gold_defense_does_not_treat_missing_month_as_an_older_month():
    gold = pd.DataFrame({"price": [100, 100, 100, 100, 100, 90]},
                        index=["2025-07", "2025-08", "2025-10", "2025-11", "2025-12", "2026-01"])
    with patch.object(calculator, "get_gold_krw_monthly", return_value=gold):
        result = calculator.get_gold_timing_for_backtest.__wrapped__(6, require_consecutive=True)
        price, ma = calculator.get_gold_month_end_ma("2026-01-31")
    assert result["2026-02"] is False
    assert price == 90 and pd.isna(ma[6])
