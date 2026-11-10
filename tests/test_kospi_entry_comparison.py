import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '기록' / '검토'))
from kospi_entry_comparison import advance_book, slot_weights, combination_weights


class PortfolioAccountingTests(unittest.TestCase):
    def test_cash_slot_keeps_its_weight(self):
        weights = slot_weights(['A', 'cash:B'])
        wealth, locked, _ = advance_book(1., {}, weights, {'A': .10}, {}, {}, cost=.005)
        self.assertAlmostEqual(wealth, 1.0475)
        self.assertFalse(locked)

    def test_locked_money_is_not_reinvested_before_release(self):
        wealth, locked, _ = advance_book(1., {}, {'A': .5, 'cash:B': .5}, {'A': 0.}, {'A': True}, {}, cost=0.)
        self.assertAlmostEqual(wealth, 1.)
        self.assertEqual(locked, {'A': .5})
        wealth, locked, log = advance_book(wealth, locked, {'C': 1.}, {'C': .10}, {}, {'A': -.10}, cost=0.)
        self.assertAlmostEqual(wealth, 1.)
        self.assertFalse(locked)
        self.assertAlmostEqual(log['free_start'], .5)
        self.assertAlmostEqual(log['released_end'], .45)

    def test_integrated_cash_slot_deduplicates_by_original_security(self):
        weights = combination_weights(['A', 'cash:B'], ['cash:B'])
        self.assertEqual(weights['통합 전략 (중복 제외 1/N)'], {'A': .5, 'cash:B': .5})
        self.assertAlmostEqual(weights['통합 전략 (중복 인정 1/N)']['cash:B'], 2/3)


if __name__ == '__main__':
    unittest.main()
