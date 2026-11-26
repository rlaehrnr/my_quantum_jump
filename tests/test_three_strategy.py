import numpy as np
import pandas as pd
import unittest

from utils.three_strategy import (
    DEFAULT_ALLOCATION, LEGS, SNOW, Allocation, backtest_window, combine, parse_history, schedule_returns,
)


def history():
    result = pd.DataFrame(0., index=["2025-01", "2025-02", "2025-03", "2025-04"], columns=LEGS)
    result["kospi"] = [.2, .4, -.1, .3]
    result["meritz"] = [0, .1, .2, 0]
    result["small"] = [0, .3, -.1, .2]
    return result


def close(actual, expected):
    unittest.TestCase().assertAlmostEqual(actual, expected, places=9)


def raises(message):
    return unittest.TestCase().assertRaisesRegex(ValueError, message)


def test_only_initial_unavailable_months_are_treated_as_cash():
    frame = history()
    frame.loc[["2025-01", "2025-03"], "mam_isa"] = np.nan
    assert backtest_window(frame, LEGS[1:], "2025-04", common=True).index.tolist() == ["2025-04"]
    assert backtest_window(frame, LEGS[1:], "2025-04", common=False).index.tolist() == ["2025-01", "2025-02"]


def test_verified_gaps_keep_historical_cash_treatment_but_stop_at_new_gaps():
    frame = history()
    frame.loc[["2025-02", "2025-04"], "mam_isa"] = np.nan
    window = backtest_window(frame, LEGS, "2025-04", common=False, verified_end="2025-03")
    assert window.index.tolist() == ["2025-01", "2025-02", "2025-03"]
    assert combine(window, dict.fromkeys(LEGS, 1)).notna().all()


def test_pair_rebalance_holds_other_sleeve_with_cashflow_untouched():
    amounts = dict(zip(LEGS, [2, 2, 0, 0, 0, 6]))
    frame = history().iloc[:2]
    metrics = schedule_returns(frame, amounts, tuple(range(1, 13)), fee=0., pair_only=True)
    expected_second = (2.2 * 1.4 + 2.2 * 1.1 + 6 * 1.3) / 10.4 - 1
    close(metrics.iloc[1], expected_second)
    np.testing.assert_allclose(schedule_returns(frame, amounts, (1, 2), fee=0., pair_only=False),
                               combine(frame, amounts))


def test_history_uses_native_fraction_and_keeps_blanks():
    rows = [
        ["2025-01", .01, "-2%", "", 0, "", .04],
        ["2025-02", .02],
    ]
    frame = parse_history(rows)
    assert frame.loc["2025-01", "meritz"] == -.02
    assert pd.isna(frame.loc["2025-01", "mam_isa"])
    assert pd.isna(frame.loc["2025-02", "small"])
    with raises("중복"):
        parse_history(rows + [rows[0]])


def test_default_allocation_round_trips_without_turning_ratio_parts_into_currency():
    assert DEFAULT_ALLOCATION.outer == (232, 195, 100)
    assert DEFAULT_ALLOCATION.inner == (130, 30, 20, 15)
    assert Allocation.decode(DEFAULT_ALLOCATION.encode()) == DEFAULT_ALLOCATION
    assert tuple(DEFAULT_ALLOCATION.weights().values()) == (232, 130, 30, 20, 15, 100)


def test_editing_snowball_inner_ratio_preserves_snowball_outer_weight():
    allocation = Allocation((232, 195, 100), (100, 30, 20, 15))
    weights = allocation.weights()
    close(sum(weights[key] for key in SNOW), 195)
    close(weights["meritz"], 195 * 100 / 165)
    assert weights["kospi"] == 232 and weights["small"] == 100
    np.testing.assert_allclose(
        combine(history(), weights),
        combine(history(), Allocation((464, 390, 200), (200, 60, 40, 30)).weights()),
    )


def test_invalid_saved_ratio_is_rejected_and_zero_snowball_is_allowed():
    for text in ("garbage", "1,2,3,4,5,6", "1,2,3,-1,2,3,4", "1,2,3,0,0,0,0", "nan,0,3,4,5,6,7"):
        with raises("비율"):
            Allocation.decode(text)
    assert Allocation((2, 0, 1), (0, 0, 0, 0)).weights()["meritz"] == 0


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            suite.addTest(unittest.FunctionTestCase(test))
    return suite
