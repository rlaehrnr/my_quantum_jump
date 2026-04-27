import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta

PRESIDENTIAL_DANGEROUS_MONTHS = {
    1: [2, 9], 2: [2, 4, 6, 9, 12], 3: [8, 9], 4: [3],
    5: [], 6: [7], 7: [6, 8, 11, 12], 8: [1, 6, 9, 10, 11]
}

def get_cycle_year(year):
    return ((year - 2021) % 8) + 1

def get_kospi_ma_all(target_date_str):
    """ 특정 날짜 기준 코스피 지수 현재가와 4, 5, 6, 10, 12개월선 반환 """
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=400)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0, {4:0, 5:0, 6:0, 10:0, 12:0}
        curr = df['Close'].iloc[-1]
        mas = {
            4: df['Close'].rolling(80).mean().iloc[-1] if len(df) >= 80 else 0,
            5: df['Close'].rolling(100).mean().iloc[-1] if len(df) >= 100 else 0,
            6: df['Close'].rolling(120).mean().iloc[-1] if len(df) >= 120 else 0,
            10: df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else 0,
            12: df['Close'].rolling(240).mean().iloc[-1] if len(df) >= 240 else 0
        }
        return curr, mas
    except:
        return 0, {4:0, 5:0, 6:0, 10:0, 12:0}

def get_kospi_timing_for_backtest(ma_months):
    ks11 = fdr.DataReader('KS11', '2010-01-01')
    ma_days = ma_months * 20 
    ks11['MA'] = ks11['Close'].rolling(ma_days).mean()
    ks11['YearMonth'] = ks11.index.to_period('M').astype(str)
    timing_df = ks11.resample('ME').last()
    timing_df['is_below_ma'] = timing_df['Close'] < timing_df['MA']
    return timing_df.set_index('YearMonth')

def get_strategy_stocks_k200(df_month, perf_pct=30, spec_12m=30):
    df_k200 = df_month.copy()
    if '시가총액' in df_k200.columns:
        df_k200['시가총액'] = pd.to_numeric(df_k200['시가총액'], errors='coerce').fillna(0)
        df_k200 = df_k200.sort_values(by='시가총액', ascending=False).head(200)

    q_perf = 1.0 - (perf_pct / 100.0)
    q_spec = 1.0 - (spec_12m / 100.0)
    
    q_1 = df_k200['1개월(%)'].quantile(q_perf)
    q_3 = df_k200['3개월(%)'].quantile(q_perf)
    q_6 = df_k200['6개월(%)'].quantile(q_perf)
    q_12 = df_k200['12개월(%)'].quantile(q_perf)
    
    t_12 = df_k200['12개월(%)'].quantile(q_spec)
    t_1 = df_k200['1개월(%)'].quantile(0.9) 
    
    cond_p = (df_k200['1개월(%)']>=q_1)&(df_k200['3개월(%)']>=q_3)&(df_k200['6개월(%)']>=q_6)&(df_k200['12개월(%)']>=q_12) & \
             (df_k200['1개월(%)']>0)&(df_k200['3개월(%)']>0)&(df_k200['6개월(%)']>0)&(df_k200['12개월(%)']>0)
             
    cond_s = (df_k200['12개월(%)']>=t_12)&(df_k200['1개월(%)']>=t_1)
    
    df_perf = df_k200[cond_p].sort_values('3개월(%)', ascending=False)
    df_spec = df_k200[cond_s].sort_values('1개월(%)', ascending=False)
    
    return df_k200, df_perf, df_spec

def run_backtest_k200(df_all, start_yr, end_yr, ma_months, apply_timing, rank_p, rank_s, perf_pct=30, spec_12m=30):
    timing_df = get_kospi_timing_for_backtest(ma_months)
    months = sorted(df_all['투자월'].dropna().unique())
    
    records = []
    trade_logs = []
    curr_now = datetime.now()
    
    for m_str in months:
        m_year, m_month = map(int, m_str.split('-'))
        if not (start_yr <= m_year <= end_yr): continue
        if m_year == curr_now.year and m_month == curr_now.month: continue
        
        m_data = df_all[df_all['투자월'] == m_str].copy()
        if m_data.empty: continue
            
        base_date = m_data['종목선정일'].iloc[0]
        base_ym = pd.to_datetime(base_date).strftime('%Y-%m') 
        
        # 💡 슬라이더에서 받은 상위 % 조건을 필터링 함수로 넘겨줍니다!
        df_k200, df_p, df_s = get_strategy_stocks_k200(m_data, perf_pct=perf_pct, spec_12m=spec_12m)
        
        neg_1m = (df_k200['1개월(%)'] < 0).sum()
        neg_3m = (df_k200['3개월(%)'] < 0).sum()
        is_bad_market = (neg_1m >= 100 and neg_3m >= 100)
        is_below_ma = timing_df.loc[base_ym, 'is_below_ma'] if base_ym in timing_df.index else False
        
        mult = 0.0 if (apply_timing and (is_bad_market or is_below_ma)) else 1.0
        
        target_p = df_p.iloc[rank_p[0]-1 : rank_p[1]]
        target_s = df_s.iloc[rank_s[0]-1 : rank_s[1]]
        
        ret_p = (target_p['이번달수익률'].mean() * mult) if not target_p.empty else 0.0
        ret_s = (target_s['이번달수익률'].mean() * mult) if not target_s.empty else 0.0
        
        combined_tickers = list(set(target_p['종목코드'].tolist() + target_s['종목코드'].tolist()))
        df_combined = m_data[m_data['종목코드'].isin(combined_tickers)]
        ret_combined = (df_combined['이번달수익률'].mean() * mult) if not df_combined.empty else 0.0
        
        records.append({
            '투자월': m_str, 'invested': (mult > 0), 
            f'🔥 퍼펙트상승 ({rank_p[0]}~{rank_p[1]}위)': ret_p, 
            f'🐎 달리는말 ({rank_s[0]}~{rank_s[1]}위)': ret_s, 
            '앙상블 (전략 50:50)': (ret_p + ret_s) / 2,
            '통합 (모든종목 동일비중)': ret_combined
        })
        
        if mult == 0.0:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍 작동', '매수순위': '-', '종목명': '현금 (투자중지)', '종목코드': '-', '수익률(%)': 0.0})
        else:
            for i, (_, row) in enumerate(target_p.iterrows()):
                trade_logs.append({'투자월': m_str, '전략': '🔥 퍼펙트 상승', '매수순위': f"{i + rank_p[0]}위", '종목명': row['종목명'], '종목코드': row['종목코드'], '수익률(%)': row['이번달수익률']})
            for i, (_, row) in enumerate(target_s.iterrows()):
                trade_logs.append({'투자월': m_str, '전략': '🐎 달리는 말', '매수순위': f"{i + rank_s[0]}위", '종목명': row['종목명'], '종목코드': row['종목코드'], '수익률(%)': row['이번달수익률']})
                
    return pd.DataFrame(records).fillna(0.0), pd.DataFrame(trade_logs)
def get_idx_kr(target_date_str):
    """ 특정 날짜 기준 코스피 지수의 최근 1개월, 3개월 수익률 계산 """
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
    except: 
        return 0.0, 0.0
