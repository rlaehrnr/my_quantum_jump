import unittest

import pandas as pd

from utils.snowball_allocation import allocation_choices, compare_allocations, comparison_window, recovery_periods


class SnowballAllocationTest(unittest.TestCase):
    def test_all_assignments_keep_money_and_honor_eligibility(self):
        choices = [('a', 'b'), ('a', 'b'), ('c',), ('d',)]
        options = allocation_choices([40, 30, 20, 10], choices)
        self.assertEqual(len(options), 4)
        assignment, amounts = options[0]
        self.assertEqual(assignment, ('a', 'a', 'c', 'd'))
        self.assertEqual(amounts, {'a': 70, 'c': 20, 'd': 10})
        distinct = allocation_choices([40, 30, 20, 10], choices, distinct=True)
        self.assertEqual(len(distinct), 2)

    def test_zero_accounts_do_not_constrain_assignments(self):
        self.assertEqual(
            allocation_choices([0, 20], [(), ('a',)], distinct=True),
            [((None, 'a'), {'a': 20})],
        )
        self.assertEqual(allocation_choices([0, 0], [('a',), ('b',)]), [])

    def test_only_recent_contiguous_confirmed_months(self):
        returns = pd.DataFrame(
            {'a': [0.1, 0.2, 0.3, 0.4], 'b': [0.0, -0.1, 0.2, 0.9]},
            index=['2026-06', '2026-08', '2026-09', '2026-10'],
        )
        self.assertEqual(
            list(comparison_window(returns, '2026-09').index),
            ['2026-08', '2026-09'],
        )

    def test_identical_weights_share_metrics_without_changing_ranks(self):
        months = pd.period_range('2026-01', periods=4, freq='M').astype(str)
        returns = pd.DataFrame({'a': [0.10, -0.10, 0.20, 0.10],
                                'b': [0.02, -0.02, 0.05, 0.03]}, index=months)
        single = [(('a', 'b'), {'a': 50, 'b': 50}), (('b', 'b'), {'b': 100})]
        duplicate = (('b', 'a'), {'b': 50, 'a': 50})
        original, other = compare_allocations(returns, single)
        first, second, swapped = compare_allocations(returns, single + [duplicate])
        self.assertEqual([first[1], second[1], swapped[1]], [original[1], other[1], original[1]])
        pd.testing.assert_series_equal(first[0]['ret'], returns.mean(axis=1))
        self.assertAlmostEqual(first[0]['worst'], -0.06)
        self.assertAlmostEqual(first[0]['tail'], -0.06)

    def test_recovery_starts_at_peak_and_tracks_open_decline(self):
        equity = pd.Series([0.80, 0.90, 1.00, 1.10, 1.05, 1.02],
                           index=pd.period_range('2025-01', periods=6, freq='M').astype(str))
        worst, latest = recovery_periods(equity)
        self.assertEqual(worst['peak'], '2024-12')
        self.assertEqual(worst['trough'], '2025-01')
        self.assertEqual(worst['recovered'], '2025-03')
        self.assertEqual(worst['months'], 3)
        self.assertEqual(latest['months'], 2)
        self.assertIsNone(latest['recovered'])


if __name__ == '__main__':
    unittest.main()
