import unittest

import numpy as np
import pandas as pd

from utils import snowball as sb


class SoExclusivePairTests(unittest.TestCase):
    def prices(self, ewy=.25, smh=.20, fdn=.10):
        months = pd.period_range('2020-01', periods=14, freq='M')
        frame = pd.DataFrame(100., index=months, columns=sb.LOAD_TICKERS)
        growth = {asset: .01 for asset in sb.SO_OFFENSE_ASSETS}
        growth.update(EWY=ewy, SMH=smh, FDN=fdn, SPY=.02)
        for asset, rate in growth.items():
            frame[asset] = 100 * (1 + rate) ** np.arange(len(months))
        return frame

    def last_signal(self, prices, use_riskoff=False):
        return sb.compute_signals_so.__wrapped__(prices, use_riskoff=use_riskoff).iloc[-1]

    def test_ewy_first_replaces_smh_with_next_eligible_asset(self):
        row = self.last_signal(self.prices())
        self.assertEqual(row['holds'], ['EWY', 'FDN'])
        self.assertIn('동시', row['reason'])

    def test_smh_first_is_preserved_instead_of_always_keeping_ewy(self):
        row = self.last_signal(self.prices(ewy=.20, smh=.25))
        self.assertEqual(row['holds'], ['SMH', 'FDN'])

    def test_replacement_skips_higher_rank_below_its_four_month_average(self):
        prices = self.prices()
        prices['FDN'] = [100.] * 10 + [200., 195., 190., 180.]
        prices['IBB'] = 100 * 1.03 ** np.arange(len(prices))
        row = self.last_signal(prices)
        self.assertGreater(row['score_FDN'], row['score_IBB'])
        self.assertLess(row['abs_FDN'], 0)
        self.assertEqual(row['holds'], ['EWY', 'IBB'])

    def test_no_eligible_replacement_keeps_only_first_asset(self):
        prices = self.prices()
        for asset in sb.SO_OFFENSE_ASSETS:
            if asset not in ['EWY', 'SMH']:
                prices[asset] = 100.
        prices['SPY'] = [100.] * 10 + [200., 195., 190., 180.]
        row = self.last_signal(prices)
        self.assertTrue(row['filter_pass'])
        self.assertEqual(row['holds'], ['EWY'])

    def test_one_pair_member_failing_absolute_momentum_does_not_refill(self):
        prices = self.prices()
        prices.loc[prices.index[-1], 'SMH'] = prices.iloc[-2]['SMH'] * .7
        row = self.last_signal(prices)
        self.assertLess(row['abs_SMH'], 0)
        self.assertEqual(row['holds'], ['EWY'])

    def test_unrelated_top_pair_is_unchanged(self):
        row = self.last_signal(self.prices(fdn=.23))
        self.assertEqual(row['holds'], ['EWY', 'FDN'])

    def test_macro_riskoff_still_takes_priority(self):
        prices = self.prices()
        for asset in sb.SIGNAL_ASSETS:
            prices[asset] = 100 * .98 ** np.arange(len(prices))
        row = self.last_signal(prices, use_riskoff=True)
        self.assertTrue(row['defensive'])
        self.assertEqual(row['holds'], ['GLD', 'IEF'])

    def test_negative_spy_filter_still_uses_defense(self):
        prices = self.prices()
        prices['SPY'] = 100 * .98 ** np.arange(len(prices))
        row = self.last_signal(prices)
        self.assertTrue(row['defensive'])
        self.assertEqual(row['holds'], ['GLD', 'IEF'])

    def test_warmup_and_missing_asset_remain_unready(self):
        self.assertIsNone(self.last_signal(self.prices().iloc[:11])['holds'])
        self.assertIsNone(self.last_signal(self.prices().drop(columns='FDN'))['holds'])


if __name__ == '__main__':
    unittest.main()
