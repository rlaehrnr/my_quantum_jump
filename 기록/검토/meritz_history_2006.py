"""또 메리츠 2006년 확장 예비 검토. 라이브 코드/data는 읽기만 한다.

python 기록/검토/meritz_history_2006.py --download
python 기록/검토/meritz_history_2006.py
원천은 기록/2026-11-10-또메리츠-2006확장/raw 에 보존한다.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '기록/2026-11-10-또메리츠-2006확장'
RAW = OUT / 'raw'
sys.path.insert(0, str(ROOT))
from utils import snowball as sb

SOURCES = {
    'cboe': 'https://www.cboe.com/markets/us/futures/market-statistics/historical-data/settlement-archive/',
    'vix_method': 'https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-vix-futures-indices.pdf',
    'vix_scaling': 'https://datashop.cboe.com/cfe-vix-volatility-index-futures-trades-quotes',
    'yahoo': 'https://query2.finance.yahoo.com/v8/finance/chart/',
}


def download():
    import requests
    import yfinance as yf
    RAW.mkdir(parents=True, exist_ok=True)
    tickers = ['TIP', 'VWO', 'VEA', 'EFA', 'VIXY', 'TQQQ', 'SQQQ', 'USD',
               'GLD', 'TLT', 'SLV', 'QQQ', 'SOXX', 'SMH', '^NDX', '^IRX', 'SI=F']
    # Yahoo downloads are sequential: its shared state can mix concurrently fetched symbols.
    for ticker in tickers:
        path = RAW / ('yf_' + ticker.replace('^', '').replace('=', '_') + '.csv')
        if path.exists():
            continue
        d = yf.Ticker(ticker).history(start='2005-01-01', end='2013-01-01', auto_adjust=True)
        if d.empty:
            raise RuntimeError(f'No Yahoo history: {ticker}')
        d.index = d.index.tz_localize(None).normalize()
        d.to_csv(path, index_label='Date')
        print('download', ticker, len(d), flush=True)

    contracts = [(y, m, c) for y in range(2005, 2014)
                 for m, c in enumerate('FGHJKMNQUVXZ', 1)]

    def fetch(item):
        year, month, code = item
        name = f'CFE_{code}{year % 100:02}_VX.csv'
        path = RAW / name
        if path.exists():
            return name, 'cached'
        url = 'https://cdn.cboe.com/resources/futures/archive/volume-and-price/' + name
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=25)
                if r.status_code in (403, 404):
                    return name, f'unavailable {r.status_code}'
                r.raise_for_status()
                if 'Trade Date' not in r.text[:150]:
                    return name, 'not csv'
                path.write_bytes(r.content)
                return name, 'ok'
            except requests.RequestException:
                if attempt == 2:
                    raise
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(fetch, contracts))
    (RAW / 'download_status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')
    print('futures files', sum(s in ('ok', 'cached') for _, s in statuses), flush=True)


def yf_series(ticker):
    name = 'yf_' + ticker.replace('^', '').replace('=', '_') + '.csv'
    return pd.read_csv(RAW / name, index_col=0, parse_dates=True)['Close'].rename(ticker)


def monthend(series):
    return series.groupby(series.index.to_period('M')).last()


def futures_panel():
    series = {}
    meta = []
    for path in sorted(RAW.glob('CFE_*_VX.csv')):
        # A few 2005 files contain an extra trailing delimiter; needed columns are stable.
        d = pd.read_csv(path, usecols=[0, 6])
        d.columns = d.columns.str.strip()
        date = pd.to_datetime(d['Trade Date'])
        settle = pd.to_numeric(d['Settle'], errors='coerce').to_numpy(dtype=float, copy=True)
        settle[date < pd.Timestamp('2007-03-26')] /= 10
        s = pd.Series(settle, index=date).sort_index()
        s = s[s > 0]
        if s.empty:
            continue
        code = path.name[4]
        year = 2000 + int(path.name[5:7])
        month = 'FGHJKMNQUVXZ'.index(code) + 1
        expiry = s.index.max()
        series[pd.Period(year=year, month=month, freq='M')] = s
        meta.append(dict(file=path.name, contract=f'{year}-{month:02}', expiry=str(expiry.date()),
                         first=str(s.index.min().date()), rows=len(s)))
    panel = pd.DataFrame(series).sort_index().sort_index(axis=1)
    (OUT / 'futures_metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    return panel, {pd.Period(x['contract'], 'M'): pd.Timestamp(x['expiry']) for x in meta}


def vix_synthetic():
    """Daily futures index approximation, with contract-number (not dollar) roll weights.

    Missing early monthly contracts are interpolated in squared prices over business days.
    An absent front contract uses spot VIX only if needed (the code instead rejects it).
    IRX prior close proxies collateral yield, 0.85% annual fund expense is subtracted.
    """
    panel, expiries = futures_panel()
    cal = panel.index
    equity_cal = yf_series('QQQ').index

    def expiry(month):
        if month in expiries:
            return expiries[month]
        # Only missing contract months use a calculated VIX settlement date.
        n = (month + 1).to_timestamp()
        fridays = pd.date_range(n, n + pd.offsets.MonthEnd(0), freq='W-FRI')
        friday = fridays[2]
        while friday not in equity_cal:
            friday -= pd.Timedelta(days=1)
        e = friday - pd.Timedelta(days=30)
        while e not in cal:
            e -= pd.Timedelta(days=1)
        return e

    def business_count(a, b):
        return int(((cal >= a) & (cal < b)).sum())

    interpolations = []

    def price(month, date):
        p = panel.at[date, month] if month in panel.columns else np.nan
        if pd.notna(p):
            return float(p)
        left = [(m, v) for m, v in panel.loc[date].dropna().items() if m < month and expiry(m) >= date]
        right = [(m, v) for m, v in panel.loc[date].dropna().items() if m > month]
        if not left or not right:
            raise RuntimeError(f'Cannot interpolate {month} on {date.date()}')
        lm, lp = left[-1]
        rm, rp = right[0]
        w = business_count(expiry(lm), expiry(month)) / business_count(expiry(lm), expiry(rm))
        interpolations.append((str(date.date()), str(month), str(lm), str(rm)))
        return float(np.sqrt(lp ** 2 + w * (rp ** 2 - lp ** 2)))

    dates = cal[(cal >= '2005-12-20') & (cal <= '2012-12-31')]
    rates = yf_series('^IRX').reindex(cal).ffill().shift(1) / 100
    values, details = [100.], []
    for prev, date in zip(dates[:-1], dates[1:]):
        # A roll cycle starts at the close on the business day before expiry.
        m = prev.to_period('M')
        prev_e = expiry(m)
        e_pos = cal.searchsorted(prev_e)
        if prev >= cal[e_pos - 1]:
            m += 1
        start = expiry(m - 1)
        end = expiry(m)
        dt = business_count(start, end)
        dr = int(((cal > prev) & (cal < end)).sum())
        w1 = dr / dt
        w2 = 1 - w1
        assert -1e-12 <= w1 <= 1 + 1e-12, (prev, m, dt, dr)
        old1, old2 = price(m, prev), price(m + 1, prev)
        new1, new2 = price(m, date), price(m + 1, date)
        r = (w1 * new1 + w2 * new2) / (w1 * old1 + w2 * old2) - 1
        days = (date - prev).days
        cash = float(rates.loc[date]) * days / 365
        net = r + cash - .0085 * days / 365
        assert net > -1
        values.append(values[-1] * (1 + net))
        details.append(dict(date=str(date.date()), front=str(m), front_weight=w1,
                            futures_return=r, cash_return=cash, net_return=net))
    pd.DataFrame(details).to_csv(OUT / 'vix_roll_daily.csv', index=False)
    (OUT / 'vix_interpolations.json').write_text(json.dumps(interpolations, indent=2), encoding='utf-8')
    return pd.Series(values, index=dates, name='VIXY')


def leverage(base, multiple, extra_spread=0.):
    """Approximation: base total returns, daily reset, funding and 0.95% expense.

    QQQ contains a small expense already; accepting that slight extra deduction is conservative.
    For inverse: cash collateral + short proceeds earn r, hence (1-L)*r funding term.
    """
    rate = yf_series('^IRX').reindex(base.index).ffill().shift(1).fillna(0) / 100
    days = base.index.to_series().diff().dt.days.fillna(0)
    returns = base.pct_change(fill_method=None).fillna(0)
    funding = (1 - multiple) * rate * days / 365
    drag = (.0095 + abs(multiple - 1) * extra_spread) * days / 365
    net = multiple * returns + funding - drag
    assert (net > -1).all()
    return (1 + net).cumprod() * 100


def splice(actual, proxy):
    """Only pre-first-actual monthly values change; anchor at the first actual observation."""
    first = actual.first_valid_index()
    assert pd.notna(proxy.get(first, np.nan)), first
    extended = proxy * actual.loc[first] / proxy.loc[first]
    extended.loc[first:] = actual.reindex(extended.loc[first:].index)
    return actual.combine_first(extended).sort_index()


def metrics(returns):
    a = np.asarray(returns, float)
    c = np.r_[1., np.cumprod(1 + a)]
    dd = c / np.maximum.accumulate(c) - 1
    trough = int(dd.argmin())
    peak = int(c[:trough + 1].argmax())
    recover = np.where(c[trough:] >= c[peak])[0]
    return dict(months=len(a), cagr=float(c[-1] ** (12 / len(a)) - 1),
                mdd=float(dd.min()), cumulative=float(c[-1] - 1),
                worst_month=float(a.min()), sharpe=float(a.mean() / a.std(ddof=0) * np.sqrt(12)),
                peak_index=peak, trough_index=trough,
                recovery_index=int(trough + recover[0]) if len(recover) else None)


def compute():
    OUT.mkdir(parents=True, exist_ok=True)
    sb._http_csv = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('local only'))
    # Current research branch has September data. Read the fetched deployment snapshot
    # into the research directory; never update the working data/ directory.
    pin = RAW / 'robot_input_commit.txt'
    if pin.exists():
        input_commit = pin.read_text().strip()
    else:
        input_commit = subprocess.check_output(['git', 'rev-parse', 'origin/main'], cwd=ROOT, text=True).strip()
        pin.write_text(input_commit + '\n', encoding='utf-8')
    code = subprocess.check_output(['git', 'show', f'{input_commit}:utils/snowball.py'], cwd=ROOT)
    assert code.replace(b'\r\n', b'\n') == (ROOT / 'utils/snowball.py').read_bytes().replace(b'\r\n', b'\n')
    (RAW / 'snowball_source.py').write_bytes(code)
    robot = RAW / 'robot_monthly'
    robot.mkdir(exist_ok=True)
    for name in [f'{t}_과거_데이터.csv' for t in sb.LOAD_TICKERS] + ['SP500_DIV.csv']:
        path = robot / name
        if not path.exists():
            path.write_bytes(subprocess.check_output(['git', 'show', f'{input_commit}:data/snowball/monthly/{name}'], cwd=ROOT))
    sb._prefetch = lambda *a, **k: None
    sb._fetch_raw_csv = lambda name: pd.read_csv(robot / name) if (robot / name).exists() else None
    live = sb.load_monthly_prices.__wrapped__(str(robot)).loc[:'2026-10']
    div = sb.load_dividend_yield.__wrapped__(str(robot)).loc[:'2026-10']
    live.to_csv(OUT / 'original_monthly_input.csv')
    div.to_csv(OUT / 'dividend_input.csv')
    synth_vix = vix_synthetic()
    synth_vix.to_csv(OUT / 'synthetic_vix_daily.csv', index_label='Date')
    qqq, soxx, smh = yf_series('QQQ'), yf_series('SOXX'), yf_series('SMH')
    # Reconstruct only missing history; preserve the robot's actual ETF observations exactly.
    proxies = {
        'VEA': monthend(yf_series('EFA')),
        'VIXY': monthend(synth_vix),
        'TQQQ': monthend(leverage(qqq, 3)),
        'SQQQ': monthend(leverage(qqq, -3)),
        'USD': monthend(leverage(soxx, 2)),
        'SLV': monthend(yf_series('SI=F')),
    }
    prices = live.reindex(pd.period_range('2005-01', '2026-10', freq='M')).copy()
    for ticker, proxy in proxies.items():
        prices[ticker] = splice(prices[ticker], proxy)
    # TIP/VWO/TLT/GLD and benchmarks already exist early enough in the local data.
    assert prices.loc['2005-12':'2026-10', sb.SIGNAL_ASSETS + sb.OFFENSE_ASSETS + sb.DEFENSE_ASSETS].notna().all().all()
    common_live = live.reindex(prices.index)
    pd.testing.assert_frame_equal(prices.where(common_live.notna()), common_live)
    prices.to_csv(OUT / 'extended_monthly_input.csv')
    sig = sb.compute_signals.__wrapped__(prices, div)
    bt = sb.run_backtest.__wrapped__(prices, sig)
    original_sig = sb.compute_signals.__wrapped__(live, div)
    original_bt = sb.run_backtest.__wrapped__(live, original_sig)
    bt.to_csv(OUT / 'extended_monthly_backtest.csv', index=False)
    sig.to_csv(OUT / 'extended_signals.csv')
    original_bt.to_csv(OUT / 'original_monthly_backtest.csv', index=False)
    months = pd.PeriodIndex(bt.hold_month, freq='M')
    assert months.equals(pd.period_range(months.min(), months.max(), freq='M'))
    # Overlap warm-up must wash out all synthetic histories.
    compare = bt.set_index('hold_month').loc[original_bt.hold_month]
    orig = original_bt.set_index('hold_month')
    assert (compare.hold == orig.hold).all()
    np.testing.assert_allclose(compare.ret_gross, orig.ret_gross, atol=1e-12)
    np.testing.assert_allclose(compare.ret_strategy.iloc[1:], orig.ret_strategy.iloc[1:], atol=1e-12)
    initial_cost_difference = float(compare.ret_strategy.iloc[0] - orig.ret_strategy.iloc[0])
    assert abs(initial_cost_difference) < 1e-12 or abs(initial_cost_difference - .0025) < 1e-12
    results = dict(sources=SOURCES, input_commit=input_commit, first_month=str(months.min()), last_month=str(months.max()),
                   original_first=str(original_bt.hold_month.iloc[0]),
                   original=metrics(original_bt.ret_strategy), extended=metrics(bt.ret_strategy),
                   overlap_months=len(orig), overlap_holdings_and_gross_identical=True,
                   overlap_first_month_entry_cost_difference=initial_cost_difference)
    periods = [('added', months.min(), pd.Period(original_bt.hold_month.iloc[0]) - 1),
               ('2006_2010', pd.Period('2006-07'), pd.Period('2010-12')),
               ('2007_2009', pd.Period('2007-01'), pd.Period('2009-12')),
               ('2008', pd.Period('2008-01'), pd.Period('2008-12'))]
    results['periods'] = {}
    for label, start, end in periods:
        mask = (months >= start) & (months <= end)
        results['periods'][label] = dict(start=str(months[mask].min()), end=str(months[mask].max()),
                                       strategy=metrics(bt.ret_strategy[mask]),
                                       qqq=metrics(bt.ret_QQQ[mask]), soxx=metrics(bt.ret_SOXX[mask]))
    results['annual'] = {str(y): dict(months=int((months.year == y).sum()),
                                     strategy=float(np.prod(1 + bt.ret_strategy[months.year == y]) - 1),
                                     qqq=float(np.prod(1 + bt.ret_QQQ[months.year == y]) - 1),
                                     soxx=float(np.prod(1 + bt.ret_SOXX[months.year == y]) - 1))
                         for y in sorted(set(months.year))}
    # Diagnostics of the VIX proxy against actual monthly returns, not price levels.
    actual_vix = live.VIXY.pct_change(fill_method=None)
    proxy_vix = monthend(synth_vix).pct_change(fill_method=None)
    pair = pd.concat([actual_vix.rename('actual'), proxy_vix.rename('synthetic')], axis=1).dropna()
    results['vix_validation'] = dict(months=len(pair), corr=float(pair.corr().iloc[0, 1]),
                                     mean_abs_monthly_error=float((pair.actual - pair.synthetic).abs().mean()),
                                     max_abs_monthly_error=float((pair.actual - pair.synthetic).abs().max()))
    pair.to_csv(OUT / 'vix_overlap_validation.csv')
    vix6 = pd.concat([(live.VIXY / live.VIXY.shift(6) - 1).rename('actual'),
                      (monthend(synth_vix) / monthend(synth_vix).shift(6) - 1).rename('synthetic')], axis=1).dropna()
    vix_trigger = lambda s: (s < 0) | (s >= .4)
    results['vix_validation']['six_month_trigger_months'] = len(vix6)
    results['vix_validation']['six_month_trigger_matches'] = int(
        (vix_trigger(vix6.actual) == vix_trigger(vix6.synthetic)).sum())
    results['leveraged_model_validation'] = {}
    for t, base, l in [('TQQQ', qqq, 3), ('SQQQ', qqq, -3), ('USD_SOXX_PROXY', soxx, 2)]:
        actual_t = 'USD' if t == 'USD_SOXX_PROXY' else t
        actual = monthend(yf_series(actual_t)).pct_change(fill_method=None)
        model = monthend(leverage(base, l)).pct_change(fill_method=None)
        pair_model = pd.concat([actual.rename('actual'), model.rename('synthetic')], axis=1).dropna()
        results['leveraged_model_validation'][t] = dict(
            months=len(pair_model), corr=float(pair_model.corr().iloc[0, 1]),
            mean_abs_monthly_error=float((pair_model.actual - pair_model.synthetic).abs().mean()),
            max_abs_monthly_error=float((pair_model.actual - pair_model.synthetic).abs().max()))
    # Dates refer to an initial NAV at the month-end preceding the first holding month.
    curve_dates = [str(months.min() - 1)] + list(bt.hold_month)
    results['drawdown_dates'] = {k.removesuffix('_index'): curve_dates[results['extended'][k]]
                                  if results['extended'][k] is not None else None
                                  for k in ['peak_index', 'trough_index', 'recovery_index']}
    # Proxy uncertainty: second semiconductor proxy and extra financing spread.
    results['sensitivity'] = {}
    for label, base, spread in [('SOXX_extra_spread_1pct', soxx, .01), ('SMH_proxy', smh, 0.)]:
        variant = prices.copy()
        for t, b, l in [('TQQQ', qqq, 3), ('SQQQ', qqq, -3), ('USD', base, 2)]:
            variant[t] = splice(live[t].reindex(prices.index), monthend(leverage(b, l, spread)))
        ss = sb.compute_signals.__wrapped__(variant, div)
        bb = sb.run_backtest.__wrapped__(variant, ss)
        assert list(bb.hold_month) == list(bt.hold_month)
        bb.to_csv(OUT / f'{label}_monthly.csv', index=False)
        mask = pd.PeriodIndex(bb.hold_month, freq='M') <= pd.Period(original_bt.hold_month.iloc[0]) - 1
        results['sensitivity'][label] = dict(extended=metrics(bb.ret_strategy), added=metrics(bb.ret_strategy[mask]))
    # Old split-adjusted CSV prices are rounded to cents. Replacing only the early
    # 2005~2012 actual history with full-precision Yahoo monthly closes checks this effect.
    revised = live.reindex(prices.index).copy()
    for t in sb.ALL_TICKERS:
        precise = monthend(yf_series(t)).loc[:'2012-12']
        precise *= revised.loc['2012-12', t] / precise.loc['2012-12']
        revised.loc[precise.index, t] = precise
    for t, proxy in proxies.items():
        revised[t] = splice(revised[t], proxy)
    revised_sig = sb.compute_signals.__wrapped__(revised, div)
    revised_bt = sb.run_backtest.__wrapped__(revised, revised_sig)
    assert list(revised_bt.hold_month) == list(bt.hold_month)
    revised_bt.to_csv(OUT / 'early_full_precision_monthly.csv', index=False)
    results['precision_diagnostic'] = dict(
        extended=metrics(revised_bt.ret_strategy),
        added=metrics(revised_bt.ret_strategy[pd.PeriodIndex(revised_bt.hold_month, freq='M') < pd.Period(original_bt.hold_month.iloc[0])]),
        year2008=float(np.prod(1 + revised_bt.ret_strategy[revised_bt.hold_month.str.startswith('2008')]) - 1))
    truncation_checks = []
    for cutoff in ['2008-08', '2009-02', '2010-12']:
        truncated = sb.compute_signals.__wrapped__(prices.loc[:cutoff], div.loc[:cutoff])
        pd.testing.assert_frame_equal(truncated, sig.loc[:cutoff])
        truncation_checks.append(cutoff)
    results['future_truncation_checks'] = truncation_checks
    # Recompute selections and returns from raw monthly windows for each reported month.
    previous = None
    err = 0.
    for row in bt.itertuples():
        m, nm = pd.Period(row.signal_month), pd.Period(row.hold_month)
        i = prices.index.get_loc(m)
        r6 = prices.loc[m, sb.SIGNAL_ASSETS] / prices.iloc[i-6][sb.SIGNAL_ASSETS] - 1
        c1 = bool((r6[sb.C1_RISK_ASSETS] < 0).all() and (r6.VIXY < 0 or r6.VIXY >= .4))
        dwindow = div.reindex(pd.period_range(m-59, m, freq='M')).dropna()
        rank = int((dwindow <= div.loc[m]).sum())
        c2 = len(dwindow) >= 48 and rank / len(dwindow) * 100 <= 10 and rank != 1
        if c1 or c2:
            scores = {t: prices.loc[m, t] / prices[t].iloc[i-11:i+1].mean() - 1 for t in sb.DEFENSE_ASSETS}
        else:
            scores = {t: prices.loc[m, t] / prices[t].iloc[i-12] - 1 for t in sb.OFFENSE_ASSETS}
        chosen = max(scores, key=scores.get)
        assert chosen == row.hold
        r = prices.loc[nm, chosen] / prices.loc[m, chosen] - 1 - (.0025 if previous != chosen else 0)
        err = max(err, abs(r - row.ret_strategy))
        previous = chosen
    results['independent_check'] = dict(months=len(bt), max_return_error=err)
    assert err < 1e-12
    (OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in OUT.rglob('*') if p.is_file() and p.name != 'sha256.json'}
    (OUT / 'sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    if args.download:
        download()
    else:
        compute()
