import unittest

import pandas as pd

from utils.snowball_allocation import allocation_choices, compare_allocations, comparison_window, recovery_periods


class SnowballAllocationTest(unittest.TestCase):
    def test_all_256_assignments_allow_repeated_strategies_and_preserve_total(self):
        keys = ('a', 'b', 'c', 'd')
        balances = (40, 30, 20, 10)
        options = allocation_choices(balances, keys)
        self.assertEqual(len({assignment for assignment, _ in options}), 256)
        self.assertEqual(options[0], (('a', 'a', 'a', 'a'), {'a': 100}))
        for assignment, amounts in options:
            self.assertEqual(sum(amounts.values()), sum(balances))
            for key in amounts:
                self.assertEqual(amounts[key], sum(balance for chosen, balance in
                                                   zip(assignment, balances) if chosen == key))

    def test_distinct_assignments_use_each_strategy_once(self):
        keys = ('a', 'b', 'c', 'd')
        balances = (40, 30, 20, 0)
        options = allocation_choices(balances, keys, distinct=True)
        self.assertEqual(len({assignment for assignment, _ in options}), 24)
        for assignment, amounts in options:
            self.assertEqual(set(assignment), set(keys))
            self.assertEqual([amounts[key] for key in assignment], list(balances))

    def test_zero_balance_does_not_affect_strategy_totals(self):
        options = allocation_choices([0, 20], ('a', 'b'))
        self.assertEqual(options, [(('a', 'a'), {'a': 20}),
                                   (('a', 'b'), {'a': 0, 'b': 20}),
                                   (('b', 'a'), {'b': 0, 'a': 20}),
                                   (('b', 'b'), {'b': 20})])
        self.assertEqual(allocation_choices([0, 0], ('a', 'b')), [])

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
