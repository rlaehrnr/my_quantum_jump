import io
import unittest

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from utils.portfolio_report import build_combined_monthly, build_combined_excel, common_portfolio_months
from utils.ui_components import get_mdd_history


class PortfolioReportTests(unittest.TestCase):
    def setUp(self):
        self.returns = pd.DataFrame({'a': [.10, -.20, .05], 'b': [.02, .04, -.01]},
                                    index=['2026-01', '2026-02', '2026-03'])
        self.defensive = pd.DataFrame({'a': [False, True, False], 'b': [True, False, True]},
                                      index=self.returns.index, dtype='boolean')

    def test_amount_weighted_returns_and_regimes_reconcile(self):
        monthly, effective, contributions = build_combined_monthly(
            self.returns, self.defensive, {'a': 3., 'b': 1.})
        np.testing.assert_allclose(monthly['종합전략'], [.08, -.14, .035])
        np.testing.assert_allclose(monthly['공격투자비율'], [.75, .25, .75])
        np.testing.assert_allclose(monthly['방어투자비율'], [.25, .75, .25])
        np.testing.assert_allclose(contributions.sum(axis=1), monthly['종합전략'])
        np.testing.assert_allclose(effective.sum(axis=1), 1.)
        self.assertAlmostEqual(monthly['자산배수'].iloc[-1], 1.08 * .86 * 1.035)

    def test_missing_strategy_renormalizes_only_available_capital(self):
        self.returns.loc['2026-01', 'b'] = np.nan
        self.defensive.loc['2026-01', 'b'] = None
        monthly, effective, _ = build_combined_monthly(
            self.returns, self.defensive, {'a': 3., 'b': 1.})
        self.assertAlmostEqual(monthly.loc['2026-01', '종합전략'], .1)
        self.assertEqual(effective.loc['2026-01', 'b'], 0)
        self.assertEqual(monthly.loc['2026-01', '공격투자비율'], 1.)

    def test_missing_regime_for_invested_strategy_is_explicit(self):
        self.defensive.loc['2026-01', 'a'] = None
        with self.assertRaisesRegex(ValueError, '국면'):
            build_combined_monthly(self.returns, self.defensive, {'a': 1.})

    def test_zero_weight_strategy_does_not_shorten_history(self):
        monthly, effective, _ = build_combined_monthly(
            self.returns, self.defensive, {'a': 0., 'b': 1.})
        self.assertEqual(list(effective.columns), ['b'])
        np.testing.assert_allclose(monthly['종합전략'], self.returns.b)

    def test_common_period_starts_after_last_internal_gap(self):
        r = pd.DataFrame({'a': [.1, np.nan, .2, .3], 'b': [.1]*4},
                         index=['2026-01', '2026-02', '2026-03', '2026-04'])
        self.assertEqual(list(common_portfolio_months(r, ['a', 'b'])), ['2026-03', '2026-04'])
        self.assertEqual(list(common_portfolio_months(r, ['a'])), ['2026-03', '2026-04'])

    def test_common_period_excludes_incomplete_final_month(self):
        r = self.returns.copy()
        r.loc['2026-03', 'a'] = np.nan
        self.assertEqual(list(common_portfolio_months(r, ['a', 'b'])), ['2026-01', '2026-02'])

    def test_common_period_detects_missing_calendar_row(self):
        r = self.returns.drop(index='2026-02')
        self.assertEqual(list(common_portfolio_months(r, ['a'])), ['2026-03'])

    def test_all_drawdown_periods_include_initial_and_unrecovered_loss(self):
        equity = pd.Series([1., .9, 1.] + [.9, 1.] * 11 + [.8],
                           index=pd.period_range('2020-01', periods=26, freq='M').astype(str))
        self.assertEqual(len(get_mdd_history(equity)), 10)
        all_periods = get_mdd_history(equity, limit=None)
        self.assertEqual(len(all_periods), 13)
        self.assertEqual(all_periods.iloc[0]['회복기간'], '진행중')
        self.assertEqual(all_periods.iloc[0]['MDD'], '-20.00%')

    def test_excel_contains_typed_values_and_all_report_sections(self):
        monthly, effective, contributions = build_combined_monthly(
            self.returns, self.defensive, {'a': 3., 'b': 1.})
        weights = pd.DataFrame({'전략': ['A', 'B'], '입력금액(만원)': [3000., 1000.], '비중': [.75, .25]})
        summary = pd.DataFrame({'지표': ['CAGR', 'MDD'], '값': [.2, -.14]})
        heatmap = pd.DataFrame({'1월': [.08], '2월': [-.14], '3월': [.035], '연수익률': [-.038692]}, index=['2026'])
        mdd = pd.DataFrame({'MDD': ['-14.00%'], '기간': ['2026-02 ~ 2026-02'], '회복기간': ['진행중']})
        data = build_combined_excel(summary, weights, monthly, effective, contributions,
                                    self.returns, heatmap, mdd, {'a': 'A', 'b': 'B'}, .0025)
        book = load_workbook(io.BytesIO(data), data_only=True)
        self.assertEqual(book.sheetnames, ['요약', '계좌비중', '월별성과', '월별기여도', '전략별수익률', '연월히트맵', 'MDD기간'])
        self.assertEqual(book['계좌비중']['C2'].value, .75)
        self.assertEqual(book['계좌비중']['C2'].number_format, '0.00%')
        self.assertAlmostEqual(book['월별성과']['B2'].value, .08)
        self.assertAlmostEqual(book['MDD기간']['A2'].value, -.14)
        self.assertGreater(len(book['연월히트맵'].conditional_formatting), 0)
        self.assertEqual(book['연월히트맵']['A2'].number_format, 'General')
        self.assertEqual(len(book['요약']._charts), 1)
        for sheet in book:
            for row in sheet:
                self.assertFalse(any(cell.data_type == 'e' for cell in row))


if __name__ == '__main__':
    unittest.main()
