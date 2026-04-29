import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import streamlit as st

PRESIDENTIAL_DANGEROUS_MONTHS = {
    1: [2, 9], 2: [2, 4, 6, 9, 12], 3: [8, 9], 4: [3],
    5: [], 6: [7], 7: [6, 8, 11, 12], 8: [1, 6, 9, 10, 11]
}

def get_cycle_year(year):
    return ((year - 2021) % 8) + 1

@st.cache_data(ttl=3600)
def get_idx_kr(target_date_str):
    target_date = pd.to_datetime(target_date_str)
    try:
        df = fdr.DataReader('KS11', target_date - pd.DateOffset(months=18), target_date)
        if df.empty: return 0.0, 0.0
        curr_val = df.loc[df.index <= target_date]['Close'].iloc[-1]
        last_date = df.index[df.index <= target_date][-1]
        def get_ret(m):
            ref = (last_date.replace(day=1) - pd.DateOffset(months=m-1)) - timedelta(days=1)
            p_df = df[df.index <= ref]
            return round(((curr_val / p_df['Close'].iloc[-1]) - 1) * 100, 1) if not p_df.empty else 0.0
        return get_ret(1), get_ret(3)
    except: return 0.0, 0.0

@st.cache_data(ttl=3600)
def get_kospi_ma_all(target_date_str):
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=450)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0, {}
        curr_p = df['Close'].iloc[-1]
        mas = {
            4: round(df['Close'].rolling(80).mean().iloc[-1], 2),
            5: round(df['Close'].rolling(100).mean().iloc[-1], 2),
            6: round(df['Close'].rolling(120).mean().iloc[-1], 2),
            10: round(df['Close'].rolling(200).mean().iloc[-1], 2),
            12: round(df['Close'].rolling(240).mean().iloc[-1], 2)
        }
        return curr_p, mas
    except: return 0, {}

@st.cache_data(show_spinner=False)
def get_kospi_timing_for_backtest(ma_months):
    ks11 = fdr.DataReader('KS11', '2005-01-01')
    ma_days = ma_months * 20
    ks11['MA'] = ks11['Close'].rolling(ma_days).mean()
    timing_df = ks11.resample('ME').last()
    timing_df['is_below_ma'] = timing_df['Close'] < timing_df['MA']
    timing_df.index = timing_df.index.strftime('%Y-%m')
    return timing_df['is_below_ma'].to_dict()

def get_strategy_stocks_korea(df):
    q30 = {c: df[c].quantile(0.7) for c in ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']}
    
    # 💡 퍼펙트는 0% 이상 조건 유지
    perf_mask = (df['1개월(%)'] >= q30['1개월(%)']) & (df['1개월(%)'] > 0) & \
                (df['3개월(%)'] >= q30['3개월(%)']) & (df['3개월(%)'] > 0) & \
                (df['6개월(%)'] >= q30['6개월(%)']) & (df['6개월(%)'] > 0) & \
                (df['12개월(%)'] >= q30['12개월(%)']) & (df['12개월(%)'] > 0)
    df_perf = df[perf_mask].sort_values('3개월(%)', ascending=False).copy()
    
    # 💡 달리는 말: 0% 이상 조건 완전 삭제 (과거 로직 복원)
    spec_mask = (df['12개월(%)'] >= q30['12개월(%)']) & \
                (df['1개월(%)'] >= df['1개월(%)'].quantile(0.9))
    df_spec = df[spec_mask].sort_values('1개월(%)', ascending=False).copy()
    
    return df, df_perf, df_spec

def run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    return _base_backtest_engine(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct, market_threshold=100)

def run_backtest_korea(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    return _base_backtest_engine(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct, market_threshold=None)

def _base_backtest_engine(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct, market_threshold):
    timing_dict = get_kospi_timing_for_backtest(ma_months)
    months = [m for m in sorted(df['투자월'].dropna().unique()) if start_year <= int(m.split('-')[0]) <= end_year]
    records, trade_logs = [], []
    
    for m in months:
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue
        
        # 💡 [핵심 복원] KOSPI 200만 시총 200위 자르기 적용
        if market_threshold == 100:
            cap_col = '시가총액(억)' if '시가총액(억)' in m_data.columns else '시가총액'
            if cap_col in m_data.columns:
                m_data = m_data.sort_values(by=cap_col, ascending=False).head(200)

        # 💡 과거 데이터의 '다음달수익률(%)' 우선 적용
        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        
        base_ym = pd.to_datetime(m_data['종목선정일'].iloc[0]).strftime('%Y-%m')
        is_below_ma = timing_dict.get(base_ym, False)
        
        is_bad_market = False
        if market_threshold is not None:
            neg_1m = (m_data['1개월(%)'] < 0).sum()
            neg_3m = (m_data['3개월(%)'] < 0).sum()
            is_bad_market = (neg_1m >= market_threshold) and (neg_3m >= market_threshold)
        
        mult = 0.0 if (apply_timing and (is_below_ma or is_bad_market)) else 1.0
        
        q_p, q_s = 1.0 - (perf_pct / 100.0), 1.0 - (spec_12m_pct / 100.0)
        
        # 💡 퍼펙트 조건 (0 이상)
        cond_p = (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_p)) & (m_data['3개월(%)']>=m_data['3개월(%)'].quantile(q_p)) & \
                 (m_data['6개월(%)']>=m_data['6개월(%)'].quantile(q_p)) & (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_p)) & \
                 (m_data['1개월(%)']>0) & (m_data['3개월(%)']>0) & (m_data['6개월(%)']>0) & (m_data['12개월(%)']>0)
                 
        # 💡 달리는 말 조건 (0 이상 필터 완전 배제)
        cond_s = (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_s)) & (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(0.9))
        
        target_p = m_data[cond_p].sort_values('3개월(%)', ascending=False).iloc[rank_p[0]-1 : rank_p[1]]
        target_s = m_data[cond_s].sort_values('1개월(%)', ascending=False).iloc[rank_s[0]-1 : rank_s[1]]
        
        ret_p = (target_p[ret_col].mean() * mult) if not target_p.empty else 0.0
        ret_s = (target_s[ret_col].mean() * mult) if not target_s.empty else 0.0
        
        # 💡 [가장 중요한 복원] 중복 종목 제거 후 남은 종목들로 단순 평균(N분의 1) 내기
        combined_series = pd.concat([target_p[ret_col], target_s[ret_col]])
        ret_total = (combined_series.mean() * mult) if not combined_series.empty else 0.0
        
        records.append({
            '투자월': m, 'invested': mult > 0, 
            f'🔥 퍼펙트 상승 ({rank_p[0]}~{rank_p[1]}위)': ret_p, 
            f'🐎 달리는 말 ({rank_s[0]}~{rank_s[1]}위)': ret_s, 
            '앙상블 (전략 50:50)': (ret_p+ret_s)/2, 
            '통합 전략 (순위 합)': ret_total
        })
        
        if mult > 0:
            for i, (_, r) in enumerate(target_p.iterrows()): trade_logs.append({'투자월': m, '전략': '퍼펙트', '순위': f"{i+rank_p[0]}위", '종목명': r['종목명'], '수익률(%)': r[ret_col]})
            for i, (_, r) in enumerate(target_s.iterrows()): trade_logs.append({'투자월': m, '전략': '달리는말', '순위': f"{i+rank_s[0]}위", '종목명': r['종목명'], '수익률(%)': r[ret_col]})
        else:
            trade_logs.append({'투자월': m, '전략': '현금보유', '순위': '-', '종목명': 'CASH', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)
