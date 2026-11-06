"""1996-06~2026-10 기존 KOSPI 전략 연속 검토. 원천 파일은 임시폴더에서 읽는다."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from kospi_overlap_audit import c, reconstruct, MOM, ENS
from kospi_top4_comparison import stats

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정'
START = '1996-06'
END = '2026-10'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def join_prefix(prefix, suffix):
    """접합일의 수준 차이만 보정해, 양쪽 기간 내 수익률을 보존한다."""
    first = suffix.index.min()
    assert first in prefix.index and prefix.loc[first] > 0
    scale = float(suffix.loc[first] / prefix.loc[first])
    return pd.concat([prefix.loc[prefix.index < first] * scale, suffix]), scale


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')

    source = args.source_dir
    legacy, manifest = reconstruct(source, end_month='2009-12', start_month=START)
    current = pd.read_csv(PREVIOUS / 'reconstructed_stocks.csv', dtype={'종목코드': str})
    stocks = pd.concat([legacy, current], ignore_index=True)
    months = pd.period_range(START, END, freq='M').astype(str).tolist()
    counts = stocks.groupby('투자월').size()
    assert counts.index.tolist() == months and counts.eq(200).all(), counts[counts.ne(200)]
    assert not stocks.duplicated(['투자월', '종목코드']).any()

    index_files = [source / f'ks11-{year}.csv' for year in range(1995, 2009)]
    krx = pd.concat([pd.read_csv(path, parse_dates=['Date']).set_index('Date')['Close'] for path in index_files]).sort_index()
    index_suffix = pd.read_csv(PREVIOUS / 'source_kospi_complete.csv', index_col=0, parse_dates=True)['Close']
    index, index_scale = join_prefix(krx, index_suffix)
    assert index.index.is_unique and (index > 0).all()
    selections = pd.to_datetime(stocks.groupby('투자월')['종목선정일'].first())
    monthly_index = index.groupby(index.index.to_period('M')).last()
    month_end_days = index.index.to_series().groupby(index.index.to_period('M')).last()
    assert (index.index.searchsorted(selections, side='right') >= 120).all()
    assert selections.tolist() == month_end_days.reindex(pd.PeriodIndex(months, freq='M') - 1).tolist()

    boe_path = source / 'gold-boe.csv'
    fx_path = source / 'dexkous.csv'
    boe = pd.read_csv(boe_path)
    gold_usd = pd.Series(pd.to_numeric(boe['XUDLGPD'], errors='coerce').to_numpy(), index=pd.to_datetime(boe['DATE'], format='%d %b %Y'))
    fx = pd.read_csv(fx_path, parse_dates=['observation_date']).set_index('observation_date')['DEXKOUS']
    fx = pd.to_numeric(fx, errors='coerce')
    # 런던·뉴욕 관측값은 한국에서 다음 달력날부터 이용 가능하다고 가정한다.
    pair = pd.concat([gold_usd, fx], axis=1, keys=['gold', 'fx'], sort=True).ffill(limit=7).dropna()
    pair.index += pd.Timedelta(days=1)
    proxy = (pair.gold * pair.fx / 31.1035).reindex(index.index, method='ffill', tolerance=pd.Timedelta(days=7)).dropna()
    gold_suffix = pd.read_csv(PREVIOUS / 'gold_daily_combined.csv', index_col=0, parse_dates=True).iloc[:, 0]
    daily_gold, gold_scale = join_prefix(proxy, gold_suffix)
    gold = daily_gold.groupby(daily_gold.index.to_period('M')).last().to_frame('price')
    gold.index = gold.index.astype(str)
    gold['ret'] = gold.price.pct_change(fill_method=None) * 100
    assert gold['ret'].reindex(months).notna().all()
    assert gold['price'].rolling(6).mean().shift(1).reindex(months).notna().all()

    missing = stocks[stocks['이번달수익률'].isna()][['투자월','종목코드','종목명']].copy()
    stocks[MOM + ['이번달수익률']] = stocks[MOM + ['이번달수익률']].fillna(0)
    stocks['시가총액(억)'] = (stocks['시가총액'] / 1e8).round(0)
    with patch.object(c, '_load_kospi_index', return_value=index.to_frame('Close')), patch.object(c, 'get_gold_krw_monthly', return_value=gold):
        returns, trades, details = c.run_backtest_k200(
            stocks, 1996, 2026, 6, True, (1,6), (1,2), 30, 30,
            trading_cost_pct=.25, gold_returns=gold.ret.to_dict(), use_gold=True,
            use_gold_ma=True, gold_ma_months=6,
        )
    assert returns['투자월'].tolist() == months
    missing_held = trades[trades['전략'].isin(['퍼펙트', '달리는말'])].merge(missing, on=['투자월','종목명'])
    original = pd.read_csv(PREVIOUS / 'monthly_returns.csv')
    common = returns.merge(original, on='투자월', suffixes=('_full','_previous'))
    compare = (common[ENS+'_full'] - common[ENS+'_previous']).abs()

    returns['KOSPI 지수(%)'] = (monthly_index.pct_change(fill_method=None) * 100).reindex(pd.PeriodIndex(months, freq='M')).to_numpy()
    assert returns['KOSPI 지수(%)'].notna().all()
    fields = [field for field in returns.columns if field not in ['투자월','invested','중지 사유']]
    annual = (1+returns[fields]/100).groupby(returns['투자월'].str[:4]).prod().sub(1).mul(100)
    intervals = [(START,END), (START,'2009-12'), ('1997-01','1998-12'), ('2008-01','2008-12'), ('2010-01',END)]
    reports = {}
    for start,end in intervals:
        segment = returns.loc[returns['투자월'].between(start,end)].reset_index(drop=True)
        reports[f'{start}~{end}'] = {field:stats(segment[field]) for field in fields}
        curve = pd.concat([pd.Series([1.]), (1+segment[ENS]/100).cumprod()],ignore_index=True)
        trough = (curve/curve.cummax()-1).idxmin()
        peak = curve.iloc[:trough+1].idxmax()
        reports[f'{start}~{end}']['drawdown'] = {
            'peak': segment['투자월'].iloc[peak-1] if peak else str(pd.Period(start)-1),
            'trough': segment['투자월'].iloc[trough-1] if trough else str(pd.Period(start)-1),
        }

    args.output.mkdir(parents=True)
    legacy.to_csv(args.output/'legacy_stocks.csv', index=False, encoding='utf-8-sig')
    returns.to_csv(args.output/'monthly_returns.csv', index=False, encoding='utf-8-sig')
    trades.to_csv(args.output/'trades.csv', index=False, encoding='utf-8-sig')
    details.to_csv(args.output/'details.csv', index=False, encoding='utf-8-sig')
    annual.to_csv(args.output/'annual_returns.csv', encoding='utf-8-sig')
    index.to_csv(args.output/'kospi_daily.csv', encoding='utf-8-sig')
    gold.to_csv(args.output/'gold_monthly.csv', encoding='utf-8-sig')
    missing_held.to_csv(args.output/'missing_selected_returns.csv', index=False, encoding='utf-8-sig')
    report = {'months':len(months),'source_manifest':manifest,
              'additional_source_sha256':{path.name:digest(path) for path in [*index_files,boe_path,fx_path]},
              'index_join':str(index_suffix.index.min().date()),'index_scale':index_scale,
              'gold_join':str(gold_suffix.index.min().date()),'gold_scale':gold_scale,
              'missing_forward_rows':len(missing),'missing_held':missing_held.to_dict('records'),
              'overlap_2010_onward_max_delta_pp':float(compare.max()),
              'overlap_2010_onward_changed_months':common.loc[compare>1e-9,'투자월'].tolist(),
              'stats':reports}
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({**{key:{ENS:value[ENS],'KOSPI':value['KOSPI 지수(%)'],'drawdown':value['drawdown']} for key,value in reports.items()}, 'missing_held':report['missing_held'],'overlap_delta':report['overlap_2010_onward_max_delta_pp']},ensure_ascii=False,indent=2),flush=True)
    print(annual[[ENS,'KOSPI 지수(%)']].round(3).to_string(),flush=True)


if __name__ == '__main__':
    main()
