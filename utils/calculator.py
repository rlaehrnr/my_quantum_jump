import pandas as pd
from datetime import datetime, timedelta

# ==========================================
# 🇰🇷 한국 주식 전용 함수
# ==========================================
PRESIDENTIAL_DANGEROUS_MONTHS = {
    1: [2, 9], 2: [2, 4, 6, 9, 12], 3: [8, 9], 4: [3],
    5: [], 6: [7], 7: [6, 8, 11, 12], 8: [1, 6, 9, 10, 11]
}

def get_cycle_year(current_year):
    years_since = current_year - 2021
    return (years_since % 8) + 1

def get_kospi_ma_all(target_date_str):
    import FinanceDataReader as fdr
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=450)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0, {}
        curr_p = df['Close'].iloc[-1]
        mas = {4: round(df['Close'].rolling(80).mean().iloc[-1], 2), 5: round(df['Close'].rolling(100).mean().iloc[-1], 2), 6: round(df['Close'].rolling(120).mean().iloc[-1], 2), 10: round(df['Close'].rolling(200).mean().iloc[-1], 2), 12: round(df['Close'].rolling(240).mean().iloc[-1], 2)}
        return curr_p, mas
    except: return 0, {}

def get_idx_kr(target_date_str):
    import FinanceDataReader as fdr
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=120)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0.0, 0.0
        curr_p = df['Close'].iloc[-1]
        df_1m = df[df.index <= target_date - pd.DateOffset(months=1)]
        ret_1m = round(((curr_p / df_1m['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m.empty else 0.0
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        return ret_1m, ret_3m
    except: return 0.0, 0.0

def get_kospi_timing_for_backtest(ma_months):
    import FinanceDataReader as fdr
    try:
        df = fdr.DataReader('KS11', '2010-01-01', datetime.today())
        df['MA'] = df['Close'].rolling(ma_months * 20).mean()
        df['Is_Below'] = df['Close'] < df['MA']
        df_monthly = df.resample('M').last()
        return {d.strftime('%Y-%m'): val for d, val in zip(df_monthly.index, df_monthly['Is_Below'])}
    except: return {}

def get_strategy_stocks_korea(df_month):
    df_calc = df_month.copy()
    q12_p = df_calc['12개월(%)'].quantile(0.7)
    q6_p, q3_p, q1_p = df_calc['6개월(%)'].quantile(0.7), df_calc['3개월(%)'].quantile(0.7), df_calc['1개월(%)'].quantile(0.7)
    cond_p = (df_calc['12개월(%)'] >= q12_p) & (df_calc['6개월(%)'] >= q6_p) & (df_calc['3개월(%)'] >= q3_p) & (df_calc['1개월(%)'] >= q1_p) & (df_calc['12개월(%)']>0) & (df_calc['6개월(%)']>0) & (df_calc['3개월(%)']>0) & (df_calc['1개월(%)']>0)
    perf_df = df_calc[cond_p].sort_values('3개월(%)', ascending=False)
    q12_s, q1_s = df_calc['12개월(%)'].quantile(0.7), df_calc['1개월(%)'].quantile(0.9)
    cond_s = (df_calc['12개월(%)'] >= q12_s) & (df_calc['1개월(%)'] >= q1_s)
    spec_df = df_calc[cond_s].sort_values('1개월(%)', ascending=False)
    return df_calc, perf_df, spec_df

def run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    timing_dict = get_kospi_timing_for_backtest(ma_months)
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        base_ym = pd.to_datetime(df_calc['종목선정일'].iloc[0]).strftime('%Y-%m')
        is_below_ma = timing_dict.get(base_ym, False)
        neg_1m, neg_3m = (df_calc['1개월(%)'] < 0).sum(), (df_calc['3개월(%)'] < 0).sum()
        is_bad_market = (neg_1m >= 100 and neg_3m >= 100)
        mult = 0.0 if (apply_timing and (is_bad_market or is_below_ma)) else 1.0
        q12_p, q6_p, q3_p, q1_p = df_calc['12개월(%)'].quantile(1-perf_pct/100), df_calc['6개월(%)'].quantile(1-perf_pct/100), df_calc['3개월(%)'].quantile(1-perf_pct/100), df_calc['1개월(%)'].quantile(1-perf_pct/100)
        cond_p = (df_calc['12개월(%)'] >= q12_p) & (df_calc['6개월(%)'] >= q6_p) & (df_calc['3개월(%)'] >= q3_p) & (df_calc['1개월(%)'] >= q1_p) & (df_calc['12개월(%)']>0) & (df_calc['6개월(%)']>0) & (df_calc['3개월(%)']>0) & (df_calc['1개월(%)']>0)
        perf_df = df_calc[cond_p].sort_values('3개월(%)', ascending=False).iloc[rank_p[0]-1:rank_p[1]]
        q12_s, q1_s = df_calc['12개월(%)'].quantile(1-spec_12m_pct/100), df_calc['1개월(%)'].quantile(0.9)
        cond_s = (df_calc['12개월(%)'] >= q12_s) & (df_calc['1개월(%)'] >= q1_s)
        spec_df = df_calc[cond_s].sort_values('1개월(%)', ascending=False).iloc[rank_s[0]-1:rank_s[1]]
        
        ret_p = perf_df['이번달수익률'].mean() * mult if not perf_df.empty else 0
        ret_s = spec_df['이번달수익률'].mean() * mult if not spec_df.empty else 0
        p_codes, s_codes = set(perf_df['종목코드']), set(spec_df['종목코드'])
        all_codes = p_codes.union(s_codes)
        ret_combined_excl = df_calc[df_calc['종목코드'].isin(all_codes)]['이번달수익률'].mean() * mult if all_codes else 0
        sum_ret = perf_df['이번달수익률'].sum() + spec_df['이번달수익률'].sum()
        total_len = len(perf_df) + len(spec_df)
        ret_combined_incl = (sum_ret / total_len * mult) if total_len > 0 else 0
        
        records.append({
            '투자월': m_str, 'invested': mult > 0, 
            f'🔥 퍼펙트 상승 ({rank_p[0]}~{rank_p[1]}위)': ret_p, 
            f'🐎 달리는 말 ({rank_s[0]}~{rank_s[1]}위)': ret_s,
            '앙상블 (50:50 전략)': (ret_p * 0.5) + (ret_s * 0.5),
            '통합 전략 (중복 제외 1/N)': ret_combined_excl,
            '통합 전략 (중복 인정 1/N)': ret_combined_incl
        })
    return pd.DataFrame(records), pd.DataFrame(trade_logs)

# ==========================================
# 🇺🇸 미국 주식 (S&P 500 / 나스닥) 전용 함수
# ==========================================
def get_us_ma_all(target_date_str, ticker='^GSPC'):
    import yfinance as yf
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=450)
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(start=start_date, end=target_date + timedelta(days=1))
        if df.empty: return 0, {}
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        curr_p = df['Close'].iloc[-1]
        mas = {4: round(df['Close'].rolling(80).mean().iloc[-1], 2), 5: round(df['Close'].rolling(100).mean().iloc[-1], 2), 6: round(df['Close'].rolling(120).mean().iloc[-1], 2), 10: round(df['Close'].rolling(200).mean().iloc[-1], 2), 12: round(df['Close'].rolling(240).mean().iloc[-1], 2)}
        return curr_p, mas
    except: return 0, {}

def get_us_idx_return(target_date_str, ticker='^GSPC'):
    import yfinance as yf
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=120)
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(start=start_date, end=target_date + timedelta(days=1))
        if df.empty: return 0.0, 0.0
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        curr_p = df['Close'].iloc[-1]
        df_1m = df[df.index <= target_date - pd.DateOffset(months=1)]
        ret_1m = round(((curr_p / df_1m['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m.empty else 0.0
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        return ret_1m, ret_3m
    except: return 0.0, 0.0

def map_english_columns(df):
    df = df.copy()
    col_mapping = {'Date': '종목선정일', 'Year': '투자연도_raw', 'Ticker': '종목코드', 'Close_Price': '종가', 'Past_1M_Return(%)': '1개월(%)', 'Past_3M_Return(%)': '3개월(%)', 'Past_6M_Return(%)': '6개월(%)', 'Past_12M_Return(%)': '12개월(%)', 'Forward_1M_Return(%)': '이번달수익률'}
    df = df.rename(columns=col_mapping)
    df = df.loc[:, ~df.columns.duplicated()]
    if '종목선정일' in df.columns:
        target_dates = pd.to_datetime(df['종목선정일']) + pd.Timedelta(days=15)
        df['투자월'], df['투자연도'] = target_dates.dt.strftime('%Y-%m'), target_dates.dt.year
    return df

def calc_us_momentum(df):
    df_calc = df.copy()
    for m in [3, 6, 12]:
        if f'{m}개월(%)' in df_calc.columns and '1개월(%)' in df_calc.columns:
            df_calc[f'{m}-1개월(%)'] = ((1 + df_calc[f'{m}개월(%)']/100) / (1 + df_calc['1개월(%)']/100) - 1) * 100
        else: df_calc[f'{m}-1개월(%)'] = 0.0
    return df_calc

def get_strategy_stocks_us(df_month, top_pct=30):
    df_calc = calc_us_momentum(df_month)
    q12_1, q6_1, q3_1 = df_calc['12-1개월(%)'].quantile(1-top_pct/100), df_calc['6-1개월(%)'].quantile(1-top_pct/100), df_calc['3-1개월(%)'].quantile(1-top_pct/100)
    strat1 = df_calc[(df_calc['12-1개월(%)'] >= q12_1) & (df_calc['6-1개월(%)'] >= q6_1) & (df_calc['12-1개월(%)'] > 0)].sort_values('6-1개월(%)', ascending=False)
    strat2 = df_calc[(df_calc['6-1개월(%)'] >= q6_1) & (df_calc['3-1개월(%)'] >= q3_1) & (df_calc['6-1개월(%)'] > 0)].sort_values('6-1개월(%)', ascending=False)
    return df_calc, strat1, strat2

# 💡 [핵심 복구] 앙상블 및 혼합 1/N 전략 재추가
def run_backtest_us(df, start_year, end_year, ma_months, apply_timing, rank_s1, rank_s2, top_pct=30):
    import yfinance as yf
    try:
        spx = yf.Ticker('^GSPC').history(start=f'{start_year-2}-01-01', end=f'{end_year}-12-31')
        if spx.index.tz is not None: spx.index = spx.index.tz_localize(None)
        spx['MA'] = spx['Close'].rolling(ma_months * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']
    except: spx = pd.DataFrame()
    
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        df_calc = df[df['투자월'] == m_str].copy()
        base_date = pd.to_datetime(m_str + '-01') - pd.Timedelta(days=5)
        is_below = spx[spx.index <= base_date]['Is_Below'].iloc[-1] if not spx.empty else False
        mult = 0.0 if (apply_timing and is_below) else 1.0
        
        _, s1_all, s2_all = get_strategy_stocks_us(df_calc, top_pct)
        s1 = s1_all.iloc[rank_s1[0]-1:rank_s1[1]]
        s2 = s2_all.iloc[rank_s2[0]-1:rank_s2[1]]
        
        r1 = s1['이번달수익률'].mean() * mult if not s1.empty else 0
        r2 = s2['이번달수익률'].mean() * mult if not s2.empty else 0
        
        s1_codes, s2_codes = set(s1['종목코드']), set(s2['종목코드'])
        all_codes = s1_codes.union(s2_codes)
        ret_combined_excl = df_calc[df_calc['종목코드'].isin(all_codes)]['이번달수익률'].mean() * mult if all_codes else 0
        sum_ret = s1['이번달수익률'].sum() + s2['이번달수익률'].sum()
        total_len = len(s1) + len(s2)
        ret_combined_incl = (sum_ret / total_len * mult) if total_len > 0 else 0
        
        records.append({
            '투자월': m_str, 'invested': mult > 0, 
            f'🔥 12-1M & 6-1M ({rank_s1[0]}~{rank_s1[1]}위)': r1, 
            f'🐎 6-1M & 3-1M ({rank_s2[0]}~{rank_s2[1]}위)': r2,
            '앙상블 (50:50 전략)': (r1 * 0.5) + (r2 * 0.5),
            '통합 전략 (중복 제외 1/N)': ret_combined_excl,
            '통합 전략 (중복 인정 1/N)': ret_combined_incl
        })
        
        if mult > 0:
            for i, (_, r) in enumerate(s1.iterrows()): trade_logs.append({'투자월': m_str, '전략': '12-1M & 6-1M', '순위': f"{i+rank_s1[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
            for i, (_, r) in enumerate(s2.iterrows()): trade_logs.append({'투자월': m_str, '전략': '6-1M & 3-1M', '순위': f"{i+rank_s2[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
        else:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)

def run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    import yfinance as yf
    try:
        spx = yf.Ticker('^GSPC').history(start=f'{start_year_c-2}-01-01', end=f'{end_year_c}-12-31')
        if spx.index.tz is not None: spx.index = spx.index.tz_localize(None)
        spx['MA'] = spx['Close'].rolling(ma_months_c * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']
    except: spx = pd.DataFrame()
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year_c <= m_yr <= end_year_c): continue
        df_calc = df[df['투자월'] == m_str].copy()
        base_date = pd.to_datetime(m_str + '-01') - pd.Timedelta(days=5)
        is_below = spx[spx.index <= base_date]['Is_Below'].iloc[-1] if not spx.empty else False
        mult = 0.0 if (apply_timing_c and is_below) else 1.0
        df_calc['스코어'] = (df_calc['1개월(%)']*w1) + (df_calc['3개월(%)']*w3) + (df_calc['6개월(%)']*w6) + (df_calc['12개월(%)']*w12)
        target = df_calc[df_calc['스코어'] >= df_calc['스코어'].quantile(1-custom_pct/100)].sort_values('스코어', ascending=False).iloc[rank_c_s-1:rank_c_e]
        
        avg_ret = target['이번달수익률'].mean() * mult if not target.empty else 0
        records.append({'투자월': m_str, 'invested': mult > 0, '커스텀 전략': avg_ret})
        
        if mult > 0:
            for i, (_, r) in enumerate(target.iterrows()): trade_logs.append({'투자월': m_str, '전략': '커스텀', '순위': f"{i+rank_c_s}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
        else:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)
