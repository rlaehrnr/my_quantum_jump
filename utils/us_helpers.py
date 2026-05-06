# utils/us_helpers.py
import pandas as pd
import numpy as np
from datetime import datetime
import FinanceDataReader as fdr
import yfinance as yf
import io
import streamlit as st
from utils.calculator import calc_us_momentum

def preprocess_us_data(df, is_daily=False):
    col_mapping = {
        'Date': '종목선정일', 'Year': '투자연도_raw', 'Ticker': '종목코드', 
        'Close_Price': '종가', 'Past_1M_Return(%)': '1개월(%)', 
        'Past_3M_Return(%)': '3개월(%)', 'Past_6M_Return(%)': '6개월(%)', 
        'Past_12M_Return(%)': '12개월(%)', 'Forward_1M_Return(%)': '이번달수익률'
    }
    for eng, kor in col_mapping.items():
        if eng in df.columns and kor in df.columns:
            df[kor] = df[kor].fillna(df[eng])
            df = df.drop(columns=[eng])
        elif eng in df.columns:
            df = df.rename(columns={eng: kor})
            
    df = df.dropna(subset=['종목코드'])
    df['종목코드'] = df['종목코드'].astype(str).replace('nan', '')
    df = df[df['종목코드'] != '']
    
    if '종목명' not in df.columns: df['종목명'] = df['종목코드']
    df['종목명'] = df['종목명'].fillna(df['종목코드'])
    df['종목명'] = np.where(df['종목명'].astype(str).str.lower() == 'nan', df['종목코드'], df['종목명'])
    
    if '시장' not in df.columns: df['시장'] = 'US'
    df['시장'] = df['시장'].fillna('US')
    df['시장'] = np.where(df['시장'].astype(str).str.lower() == 'nan', 'US', df['시장'])
    
    df['통합티커'] = df['시장'] + ":" + df['종목코드']

    if not is_daily:
        df['종목선정일'] = pd.to_datetime(df['종목선정일'], errors='coerce')
        df = df.dropna(subset=['종목선정일'])
        target_dates = df['종목선정일'] + pd.Timedelta(days=15)
        df['투자월'] = target_dates.dt.strftime('%Y-%m')
        df['투자연도'] = target_dates.dt.year
    else:
        if '기준일' in df.columns:
            df['기준일'] = pd.to_datetime(df['기준일'], errors='coerce')

    target_cols = ['시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']
    for col in target_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        else: df[col] = 0
        
    return df

def add_naver_links(df):
    naver_exceptions = {'CIEN': '.K', 'COHR': '.K', 'EQNR': '.K', 'DELL': '.K'}
    def get_naver_ticker(code): return f"{code}{naver_exceptions.get(code, '.O')}"
    
    df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{get_naver_ticker(r['종목코드'])}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
    df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/foreign/stock/{get_naver_ticker(r['종목코드'])}#{r['종목명']}", axis=1)
    return df

@st.cache_data(ttl=3600)
def robust_get_us_ma_all(target_date_str, ticker='^GSPC'):
    try:
        target_date = pd.to_datetime(target_date_str).normalize()
        df = pd.DataFrame()
        try:
            df = yf.Ticker(ticker).history(period="2y")
            if not df.empty and df.index.tz is not None: df.index = df.index.tz_localize(None)
        except: pass
        if df.empty:
            df = fdr.DataReader('US500' if ticker == '^GSPC' else 'IXIC')
        if df.empty: return 0.0, {}
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df.index <= target_date]
        if df.empty: return 0.0, {}
        
        curr_p = df['Close'].iloc[-1]
        mas = {
            4: round(df['Close'].rolling(80).mean().iloc[-1], 2),
            5: round(df['Close'].rolling(100).mean().iloc[-1], 2),
            6: round(df['Close'].rolling(120).mean().iloc[-1], 2),
            10: round(df['Close'].rolling(200).mean().iloc[-1], 2),
            12: round(df['Close'].rolling(240).mean().iloc[-1], 2)
        }
        return curr_p, mas
    except Exception: return 0.0, {}

@st.cache_data(ttl=3600)
def robust_get_us_idx_return(target_date_str, ticker='^GSPC'):
    try:
        target_date = pd.to_datetime(target_date_str).normalize()
        df = pd.DataFrame()
        try:
            df = yf.Ticker(ticker).history(period="2y")
            if not df.empty and df.index.tz is not None: df.index = df.index.tz_localize(None)
        except: pass
        if df.empty:
            df = fdr.DataReader('US500' if ticker == '^GSPC' else 'IXIC')
        if df.empty: return 0.0, 0.0
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df.index <= target_date]
        if df.empty: return 0.0, 0.0
        
        curr_p = df['Close'].iloc[-1]
        df_1m = df[df.index <= target_date - pd.DateOffset(months=1)]
        ret_1m = round(((curr_p / df_1m['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m.empty else 0.0
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        return ret_1m, ret_3m
    except Exception: return 0.0, 0.0

@st.cache_data(ttl=86400, show_spinner=False)
def get_spx_history_cached():
    try:
        spx = pd.DataFrame()
        try:
            spx = yf.Ticker('^GSPC').history(start='1998-01-01')
            if not spx.empty and spx.index.tz is not None: spx.index = spx.index.tz_localize(None)
        except: pass
        if spx.empty: spx = fdr.DataReader('US500', '1998-01-01')
        if not spx.empty: spx.index = pd.to_datetime(spx.index).normalize()
        return spx
    except: return pd.DataFrame()

@st.cache_data(show_spinner=False)
def generate_excel_report_cached(settings_tuple, df_stats, df_monthly, df_cum_ret, df_trade):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_set = pd.DataFrame(list(settings_tuple), columns=['설정 항목', '값'])
        df_set.to_excel(writer, sheet_name='요약_및_통계', index=False, startrow=0)
        df_stats.to_excel(writer, sheet_name='요약_및_통계', index=False, startrow=len(df_set) + 2)
        df_monthly.to_excel(writer, sheet_name='월별_수익률', index=False)
        df_mdd = ((df_cum_ret / df_cum_ret.cummax()) - 1) * 100
        df_mdd.reset_index().to_excel(writer, sheet_name='전략별_MDD', index=False)
        df_cum_ret.reset_index().to_excel(writer, sheet_name='누적_수익률', index=False)
        if not df_trade.empty:
            df_trade.to_excel(writer, sheet_name='상세_매매내역', index=False)
    return output.getvalue()

def get_strategy_stocks_us_custom(df_month, top_n_12=150, top_n_6=150, top_n_3=150):
    df_calc = calc_us_momentum(df_month)
    df_12_valid = df_calc[df_calc['12-1개월(%)'] > 0]
    df_6_valid = df_calc[df_calc['6-1개월(%)'] > 0]
    df_3_valid = df_calc[df_calc['3-1개월(%)'] > 0]
    
    top_12 = df_12_valid.sort_values('12-1개월(%)', ascending=False).head(top_n_12)
    top_6 = df_6_valid.sort_values('6-1개월(%)', ascending=False).head(top_n_6)
    top_3 = df_3_valid.sort_values('3-1개월(%)', ascending=False).head(top_n_3)
    
    strat1 = top_12[top_12['종목코드'].isin(top_6['종목코드'])].sort_values('6-1개월(%)', ascending=False)
    strat2 = top_6[top_6['종목코드'].isin(top_3['종목코드'])].sort_values('6-1개월(%)', ascending=False)
    
    return df_calc, strat1, strat2

@st.cache_data(show_spinner=False)
def run_backtest_us_fast(df, start_year, end_year, ma_months, apply_timing, rank_s1, rank_s2, top_n_12, top_n_6, top_n_3, spx):
    if not spx.empty:
        spx['MA'] = spx['Close'].rolling(ma_months * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']
        
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        
        base_date = pd.to_datetime(m_str + '-01') - pd.Timedelta(days=5)
        is_below = False
        if not spx.empty:
            past_spx = spx[spx.index <= base_date]
            if not past_spx.empty: is_below = past_spx['Is_Below'].iloc[-1]
                
        mult = 0.0 if (apply_timing and is_below) else 1.0
        
        _, s1_all, s2_all = get_strategy_stocks_us_custom(df_calc, top_n_12, top_n_6, top_n_3)
        s1 = s1_all.iloc[rank_s1[0]-1:rank_s1[1]] if not s1_all.empty else pd.DataFrame()
        s2 = s2_all.iloc[rank_s2[0]-1:rank_s2[1]] if not s2_all.empty else pd.DataFrame()
        
        r1 = s1['이번달수익률'].mean() * mult if not s1.empty else 0
        r2 = s2['이번달수익률'].mean() * mult if not s2.empty else 0
        
        s1_codes = set(s1['종목코드']) if not s1.empty else set()
        s2_codes = set(s2['종목코드']) if not s2.empty else set()
        all_codes = s1_codes.union(s2_codes)
        ret_combined_excl = df_calc[df_calc['종목코드'].isin(all_codes)]['이번달수익률'].mean() * mult if all_codes else 0
        
        sum_ret = (s1['이번달수익률'].sum() if not s1.empty else 0) + (s2['이번달수익률'].sum() if not s2.empty else 0)
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
            if not s1.empty:
                for i, (_, r) in enumerate(s1.iterrows()): trade_logs.append({'투자월': m_str, '전략': '12-1M & 6-1M', '순위': f"{i+rank_s1[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
            if not s2.empty:
                for i, (_, r) in enumerate(s2.iterrows()): trade_logs.append({'투자월': m_str, '전략': '6-1M & 3-1M', '순위': f"{i+rank_s2[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
        else:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)
