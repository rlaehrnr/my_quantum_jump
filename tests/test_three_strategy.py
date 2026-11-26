import numpy as np
import pandas as pd
import unittest

from utils.three_strategy import (
    LEGS, backtest_window, combine, parse_history, schedule_returns,
)
from utils.three_strategy_store import allocation_row, read_amounts, save_amounts


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


class FakeSheet:
    def __init__(self, row=None):
        self.row = row

    def get(self, _address, **_kwargs):
        return [self.row] if self.row else []

    def update(self, *, range_name, values, **_kwargs):
        self.address = range_name
        self.row = values[0]


def test_month_setting_write_only_updates_that_month_and_refuses_misalignment():
    s = FakeSheet()
    amounts = dict(zip(LEGS, [20, 3, 4, 5, 6, 1.5]))
    save_amounts(s, "2026-12", amounts)
    row = allocation_row("2026-12")
    assert s.address == f"A{row}:G{row}"
    assert read_amounts(s, "2026-12") == amounts
    s.row[0] = "2026-11"
    with raises("투자월"):
        save_amounts(s, "2026-12", amounts)


def test_blank_or_partial_amount_row_is_not_silently_used():
    with raises("여섯"):
        read_amounts(FakeSheet(["2026-11", 1, 0]), "2026-11")
    assert read_amounts(FakeSheet(["2026-11"]), "2026-11") is None


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            suite.addTest(unittest.FunctionTestCase(test))
    return suite
