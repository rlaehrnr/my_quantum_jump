import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import FinanceDataReader as fdr
import yfinance as yf
import io
import streamlit as st

def preprocess_us_data(df, is_daily=False):
    col_mapping = {
        'Date': '종목선정일', 'Year': '투자연도_raw', 'Ticker': '종목코드', 
        'Close_Price': '종가', 'Past_1M_Return(%)': '1개월(%)', 
        'Past_3M_Return(%)': '3개월(%)', 'Past_6M_Return(%)': '6개월(%)', 
        'Past_12M_Return(%)': '12개월(%)', 'Forward_1M_Return(%)': '이번달수익률',
        '기준일(월말)': '종목선정일', '기준가': '종가', '다음달수익률(%)': '이번달수익률'
    }
    
    # 💡 [핵심 복구] 과거 SP500 데이터가 증발하지 않도록 데이터를 안전하게 병합하는 로직 원상복구
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
    
    # 💡 시장 컬럼명이 영어(Market/Exchange 등)여도 '시장'으로 인식
    if '시장' not in df.columns:
        for alt in ['Market', 'market', 'MARKET', 'Exchange', 'exchange', 'EXCHANGE', '거래소']:
            if alt in df.columns:
                df = df.rename(columns={alt: '시장'})
                break
    if '시장' not in df.columns: df['시장'] = 'US'
    # 💡 옛 파일('거래소')과 신 파일('시장')을 함께 concat하면 두 컬럼이 공존 → 시장이 비었거나 'US'인 행을
    #    거래소 등 대체 컬럼 값으로 채운다(그래야 옛 달도 NASDAQ:/NYSE: 로 구분 표시됨)
    for alt in ['거래소', 'Market', 'market', 'MARKET', 'Exchange', 'exchange', 'EXCHANGE']:
        if alt in df.columns and alt != '시장':
            need = df['시장'].isna() | df['시장'].astype(str).str.strip().str.lower().isin(['nan', '', 'us'])
            df.loc[need, '시장'] = df.loc[need, alt]
    df['시장'] = df['시장'].fillna('US')
    df['시장'] = np.where(df['시장'].astype(str).str.strip().str.lower().isin(['nan', '']), 'US', df['시장'])
    
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
    exceptions_k = ['CIEN', 'COHR', 'EQNR', 'DELL', 'HSBC']
    
    def get_naver_ticker(row):
        code_str = str(row['종목코드']).strip()
        market_str = str(row.get('시장', '')).upper()
        
        if code_str in exceptions_k:
            return f"{code_str}.K"
        elif 'NASDAQ' in market_str or '나스닥' in market_str:
            return f"{code_str}.O"
        else:
            return code_str 
            
    df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{get_naver_ticker(r)}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
    # 종목명에 '%'가 있으면(예: 채권 '5.350%') Streamlit LinkColumn이 URL을 못 읽어 원본 링크가 그대로 노출됨 → 방어 치환
    df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/foreign/stock/{get_naver_ticker(r)}#{str(r['종목명']).replace('#', ' ').replace('%', '％')}", axis=1)
    return df

@st.cache_data(ttl=3600)
def robust_get_us_ma_all(target_date_str, ticker='^GSPC'):
    try:
        target_date = pd.to_datetime(target_date_str).normalize()
        start_date = target_date - pd.Timedelta(days=450)
        end_date = target_date + pd.Timedelta(days=2)
        
        df = pd.DataFrame()
        try:
            df = yf.Ticker(ticker).history(start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'))
            if not df.empty and df.index.tz is not None: df.index = df.index.tz_localize(None)
        except: pass
        if df.empty:
            df = fdr.DataReader('US500' if ticker == '^GSPC' else 'IXIC', start_date, end_date)
        if df.empty: return 0.0, {}
        
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df.index <= target_date]
        if df.empty: return 0.0, {}
        
        curr_p = df['Close'].iloc[-1]
        mas = {
            4: round(df['Close'].rolling(80).mean().iloc[-1], 2) if len(df) >= 80 else None,
            5: round(df['Close'].rolling(100).mean().iloc[-1], 2) if len(df) >= 100 else None,
            6: round(df['Close'].rolling(120).mean().iloc[-1], 2) if len(df) >= 120 else None,
            10: round(df['Close'].rolling(200).mean().iloc[-1], 2) if len(df) >= 200 else None,
            12: round(df['Close'].rolling(240).mean().iloc[-1], 2) if len(df) >= 240 else None
        }
        return curr_p, mas
    except Exception: return 0.0, {}

@st.cache_data(ttl=3600)
def robust_get_us_idx_return(target_date_str, ticker='^GSPC'):
    try:
        target_date = pd.to_datetime(target_date_str).normalize()
        # 데이터 여유있게 수집 (MTD 계산을 위해 최소 40일 이상 필요)
        start_date = target_date - pd.Timedelta(days=150)
        end_date = target_date + pd.Timedelta(days=2)
        
        df = pd.DataFrame()
        try:
            df = yf.Ticker(ticker).history(start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'))
            if not df.empty and df.index.tz is not None: df.index = df.index.tz_localize(None)
        except: pass
        if df.empty:
            df = fdr.DataReader('US500' if ticker == '^GSPC' else 'IXIC', start_date, end_date)
        if df.empty: return 0.0, 0.0
        
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df.index <= target_date]
        if df.empty: return 0.0, 0.0
        
        curr_p = df['Close'].iloc[-1]
        
        # 💡 [핵심 수정: MTD 로직] 이번 달 1일보다 이전 날짜 중 가장 마지막 거래일(즉, 전월 말일) 찾기
        first_day_of_month = target_date.replace(day=1)
        prev_month_end_df = df[df.index < first_day_of_month]
        
        ret_mtd = 0.0
        if not prev_month_end_df.empty:
            prev_month_end_price = prev_month_end_df['Close'].iloc[-1]
            ret_mtd = round(((curr_p / prev_month_end_price) - 1) * 100, 2)
            
        # 3개월 수익률은 기존의 Rolling 방식을 유지 (필요 시 수정 가능)
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        
        return ret_mtd, ret_3m
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
def get_spy_timing_map(ma_months):
    """SPY 월봉 N개월선 이탈 신호 → {투자월'YYYY-MM': True(이탈=방어)}.

    커밋된 스노우볼 SPY 월봉(raw URL, 1993~)을 사용 → 야후(^GSPC) 차단/실패와
    무관하게 안정적. 신호는 '전월 말' 기준(투자월 m → 전월 종가 vs N개월선),
    라이브 결정 시점(월말 선정)과 동일하게 1개월 시프트."""
    import io as _io, urllib.request as _u, urllib.parse as _up
    raw = ("https://raw.githubusercontent.com/rlaehrnr/my_quantum_jump/main/data/snowball/monthly/"
           + _up.quote("SPY_과거_데이터.csv"))
    try:
        txt = _u.urlopen(raw, timeout=10).read().decode('utf-8-sig')
        d = pd.read_csv(_io.StringIO(txt)); d.columns = [c.strip() for c in d.columns]
        d['날짜'] = pd.to_datetime(d['날짜']); d = d.sort_values('날짜').set_index('날짜')
        s = d['종가']; s.index = s.index.to_period('M')
        below = (s < s.rolling(int(ma_months)).mean())
        out = {}
        for per in below.index:
            if pd.notna(below.loc[per]):
                out[(per + 1).strftime('%Y-%m')] = bool(below.loc[per])   # 전월 신호 → 다음 투자월
        return out
    except Exception:
        return {}


def _spy_is_below(m_str, ma_months, spx):
    """SPY 마켓타이밍 이탈 여부. 월봉 맵(안정적) 우선, 없으면 일봉 spx 폴백."""
    v = get_spy_timing_map(ma_months).get(m_str)
    if v is not None:
        return bool(v)
    if spx is not None and not getattr(spx, 'empty', True):
        first_of_m = pd.to_datetime(m_str + '-01')
        past = spx[spx.index < first_of_m]
        if not past.empty:
            return bool(past['Is_Below'].iloc[-1])
    return False

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

def calc_us_momentum(df):
    df_calc = df.copy()
    for m in [3, 6, 12]:
        if f'{m}개월(%)' in df_calc.columns and '1개월(%)' in df_calc.columns:
            df_calc[f'{m}-1개월(%)'] = ((1 + df_calc[f'{m}개월(%)']/100) / (1 + df_calc['1개월(%)']/100) - 1) * 100
        else: df_calc[f'{m}-1개월(%)'] = 0.0
    return df_calc

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
    
    # 💡 완벽하게 3개(원본, 12-1&6-1, 6-1&3-1)만 리턴합니다.
    return df_calc, strat1, strat2

def get_triple_momentum_us(df_month, cutoff, mode='pct'):
    """
    3-1 · 6-1 · 12-1 각각 상위(cutoff)에 든 종목의 '3중 교집합'을 12-1 내림차순으로 정렬해 반환.

    mode='pct'  → cutoff는 상위 %  (예: 30 → 각 지표 상위 30% 종목)
    mode='rank' → cutoff는 상위 N위 (예: 150 → 각 지표 상위 150종목)

    반환: 교집합 종목 DataFrame (12-1개월(%) 내림차순, 원본 컬럼 + 모멘텀 컬럼 포함)
    """
    d = calc_us_momentum(df_month)
    cols = ['3-1개월(%)', '6-1개월(%)', '12-1개월(%)']
    code_sets = []
    for c in cols:
        s = d.dropna(subset=[c])
        if s.empty:
            code_sets.append(set())
            continue
        if mode == 'pct':
            thr = s[c].quantile(1 - cutoff / 100.0)
            picked = s[s[c] >= thr]
        else:  # rank
            picked = s.sort_values(c, ascending=False).head(int(cutoff))
        code_sets.append(set(picked['종목코드']))

    inter = set.intersection(*code_sets) if code_sets else set()
    out = d[d['종목코드'].isin(inter)].sort_values('12-1개월(%)', ascending=False).reset_index(drop=True)
    return out

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
        is_below = _spy_is_below(m_str, ma_months, spx)
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

@st.cache_data(show_spinner=False)
def run_backtest_triple_us(df, start_year, end_year, ma_months, apply_timing, top_n_cutoff, rank_s, rank_e, spx):
    """
    [3중 교집합 전략 백테스트]
    매월: 3-1 · 6-1 · 12-1 각 상위 top_n_cutoff위에 모두 든 종목(교집합)을
          12-1 내림차순 정렬 → rank_s ~ rank_e 순위 매수 → 다음달(이번달수익률) 성과 집계.
    apply_timing: S&P500 (ma_months*20)일선 이탈 시 현금(0%).
    """
    if not spx.empty:
        spx = spx.copy()
        spx['MA'] = spx['Close'].rolling(ma_months * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']

    strat_name = '🎯 3·6·12 교집합 (12-1 정렬)'
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        df_m = df[df['투자월'] == m_str].copy()
        if df_m.empty: continue

        base_date = pd.to_datetime(m_str + '-01') - pd.Timedelta(days=5)
        is_below = _spy_is_below(m_str, ma_months, spx)
        mult = 0.0 if (apply_timing and is_below) else 1.0

        picks_all = get_triple_momentum_us(df_m, cutoff=top_n_cutoff, mode='rank')
        picks = picks_all.iloc[rank_s - 1:rank_e] if not picks_all.empty else pd.DataFrame()
        ret = picks['이번달수익률'].mean() * mult if not picks.empty else 0.0

        records.append({'투자월': m_str, 'invested': mult > 0, strat_name: ret})

        if mult > 0 and not picks.empty:
            for i, (_, r) in enumerate(picks.iterrows()):
                trade_logs.append({'투자월': m_str, '전략': '3·6·12교집합', '순위': f"{i+rank_s}위",
                                   '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r['이번달수익률']})
        elif mult <= 0:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-',
                               '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
        else:
            trade_logs.append({'투자월': m_str, '전략': '교집합없음', '순위': '-',
                               '종목명': '해당종목없음', '수익률(%)': 0.0})

    return pd.DataFrame(records), pd.DataFrame(trade_logs)

@st.cache_data(show_spinner=False)
def run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    spx = get_spx_history_cached()
    if not spx.empty:
        spx['MA'] = spx['Close'].rolling(ma_months_c * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']
        
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year_c <= m_yr <= end_year_c): continue
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        
        base_date = pd.to_datetime(m_str + '-01') - pd.Timedelta(days=5)
        is_below = _spy_is_below(m_str, ma_months_c, spx)
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


# ==========================================================================
# 🛡️ 멀티4 (스노우볼 cond1) 위험회피 신호
#   규칙: (TIP·VWO·VEA 6M 수익률 모두 음수) AND (VIXY 6M < 0  OR  VIXY 6M ≥ +40%)
#   데이터: data/snowball/monthly/{TICKER}_과거_데이터.csv  (컬럼: 날짜, 종가 / 월말)
#   타이밍: 신호월 m → 투자월 m+1 (스노우볼과 동일 정렬)
#   VIXY 상장(2011-01)+6M 이후부터 유효. 그 전 투자월은 맵에 키 없음 → 호출측 기본 False
#           (= 상장 이전 구간은 SPY 마켓타이밍만 적용)
# ==========================================================================
_SNOWBALL_RAW_BASE = "https://raw.githubusercontent.com/rlaehrnr/my_quantum_jump/main/data/snowball/monthly/"
_MULTI4_TICKERS = ['TIP', 'VWO', 'VEA', 'VIXY']
VIXY_SPIKE = 0.40


def _load_snowball_signal_series(ticker):
    """스노우볼 신호 ETF 월말 종가 Series(index=Period['M']). raw GitHub 우선 + 로컬 폴백."""
    import urllib.parse, os, glob, re
    fname = f"{ticker}_과거_데이터.csv"
    df = None
    try:
        url = _SNOWBALL_RAW_BASE + urllib.parse.quote(fname)
        df = pd.read_csv(url, encoding='utf-8-sig')
    except Exception:
        df = None
    if df is None or df.empty:
        want = re.sub(r'[\s_]+', '', fname)
        for p in glob.glob('data/snowball/monthly/*.csv'):
            if re.sub(r'[\s_]+', '', os.path.basename(p)) == want:
                try:
                    df = pd.read_csv(p, encoding='utf-8-sig')
                except Exception:
                    df = None
                break
    if df is None or df.empty:
        return pd.Series(dtype=float)
    df.columns = [c.strip() for c in df.columns]
    if '날짜' not in df.columns or '종가' not in df.columns:
        return pd.Series(dtype=float)
    df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
    df = df.dropna(subset=['날짜'])
    s = df.set_index('날짜')['종가'].astype(float).sort_index()
    s.index = s.index.to_period('M')
    return s[~s.index.duplicated(keep='last')]


@st.cache_data(ttl="6h", show_spinner=False)
def get_multi4_cond1_map():
    """
    멀티4 위험회피 신호 → {투자월'YYYY-MM': True/False}.
    유효(4종 6M 모두 존재)한 투자월만 키로 포함. 상장 전 월은 키 없음 → 호출측 기본 False.
    """
    series = {}
    for t in _MULTI4_TICKERS:
        s = _load_snowball_signal_series(t)
        if s.empty:
            return {}
        series[t] = s
    px = pd.DataFrame(series).sort_index()
    r6 = px / px.shift(6) - 1.0
    base_neg = (r6[['TIP', 'VWO', 'VEA']] < 0).all(axis=1)
    vixy = r6['VIXY']
    ready = r6[_MULTI4_TICKERS].notna().all(axis=1)
    cond1 = base_neg & ((vixy < 0) | (vixy >= VIXY_SPIKE))
    out = {}
    for period, is_ready in ready.items():
        if not is_ready:
            continue
        inv = (period + 1).strftime('%Y-%m')   # 신호월+1 = 투자월
        out[inv] = bool(cond1.loc[period])
    return out


def get_multi4_start_ym():
    """멀티4가 실제로 작동하기 시작하는 첫 투자월('YYYY-MM'). 데이터 없으면 None."""
    m = get_multi4_cond1_map()
    return min(m.keys()) if m else None


@st.cache_data(show_spinner=False)
def run_backtest_triple_us_m4(df, start_year, end_year, ma_months, apply_timing, use_multi4, top_n_cutoff, rank_s, rank_e, spx):
    """
    3중 교집합 전략(12-1 정렬 → rank_s~rank_e 매수) + 방어 필터.
    방어 = apply_timing AND ( SPY (ma_months*20)일선 이탈  OR  멀티4 cond1 ).
    use_multi4=False면 SPY 필터만(= run_backtest_triple_us와 동일).
    멀티4는 VIXY 상장+6M 이후 투자월에만 작동(그 전은 SPY만).
    """
    cond1_map = get_multi4_cond1_map() if use_multi4 else {}
    if not spx.empty:
        spx = spx.copy()
        spx['MA'] = spx['Close'].rolling(ma_months * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']

    strat_name = '🛡️ 3·6·12 교집합 + 멀티4' if use_multi4 else '🎯 3·6·12 교집합 (12-1 정렬)'
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        df_m = df[df['투자월'] == m_str].copy()
        if df_m.empty: continue

        # SPY 마켓타이밍 신호 = '투자월 시작 직전의 마지막 거래일'(=전월 말)의 종가 vs 240일선.
        # (엉성한 '월초-5일' 근사치 대신 데이터에서 직접 월말을 잡음 → 라이브(종목선정일=월말)와 동일)
        first_of_m = pd.to_datetime(m_str + '-01')
        is_below = _spy_is_below(m_str, ma_months, spx)
        is_m4 = bool(cond1_map.get(m_str, False))
        defense = bool(apply_timing and (is_below or is_m4))
        mult = 0.0 if defense else 1.0

        picks_all = get_triple_momentum_us(df_m, cutoff=top_n_cutoff, mode='rank')
        picks = picks_all.iloc[rank_s - 1:rank_e] if not picks_all.empty else pd.DataFrame()
        offense_ret = picks['이번달수익률'].mean() if not picks.empty else 0.0   # 반사실: 방어 안 하고 공격했을 때 수익률
        ret = offense_ret * mult                                                # 실제(방어면 0)

        if not defense:
            stop_reason = ''
        elif is_below and is_m4:
            stop_reason = 'S&P500 240일선 이탈 + 멀티4'
        elif is_m4:
            stop_reason = '멀티4 필터'
        else:
            stop_reason = 'S&P500 240일선 이탈'

        records.append({
            '투자월': m_str,
            'invested': mult > 0,
            strat_name: ret,                                # 정밀도 유지(누적계산용) — 방어월은 0
            '중지사유': stop_reason,
            '공격시수익률(%)': round(offense_ret, 2),          # 방어했더라도 '공격했다면' 수익률
            '공격-방어차이(%p)': round(offense_ret - ret, 2),  # 양수=방어가 손해, 음수=방어가 이득
        })

        if mult > 0 and not picks.empty:
            for i, (_, r) in enumerate(picks.iterrows()):
                trade_logs.append({'투자월': m_str, '전략': '3·6·12교집합', '순위': f"{i+rank_s}위",
                                   '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r['이번달수익률']})
        elif defense:
            reason = '마켓타이밍+멀티4' if (is_below and is_m4) else ('멀티4' if is_m4 else '마켓타이밍')
            trade_logs.append({'투자월': m_str, '전략': reason, '순위': '-',
                               '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
        else:
            trade_logs.append({'투자월': m_str, '전략': '교집합없음', '순위': '-',
                               '종목명': '해당종목없음', '수익률(%)': 0.0})

    return pd.DataFrame(records), pd.DataFrame(trade_logs)


@st.cache_data(show_spinner=False)
def get_benchmark_monthly_returns():
    """
    SPY · QQQ 월간 수익률(%) → DataFrame(index='YYYY-MM', columns=['SPY','QQQ']).
    1순위 yfinance(전체기간, 배당반영), 2순위 FDR, 3순위 스노우볼 CSV(2005~).
    투자월 m의 벤치마크 = 해당 캘린더월 종가수익률(전략 '이번달수익률'과 동일 정렬).
    """
    cols = {}
    for name in ['SPY', 'QQQ']:
        s = None
        try:
            h = yf.Ticker(name).history(start='1998-01-01')
            if not h.empty:
                if h.index.tz is not None:
                    h.index = h.index.tz_localize(None)
                s = h['Close']
        except Exception:
            s = None
        if s is None or len(s) == 0:
            try:
                d = fdr.DataReader(name, '1998-01-01')
                if not d.empty:
                    s = d['Close']
            except Exception:
                s = None
        if s is not None and len(s) > 0:
            s = pd.Series(pd.to_numeric(s.values, errors='coerce'), index=pd.to_datetime(s.index)).dropna()
            m = s.resample('ME').last()
            m.index = m.index.to_period('M')
            cols[name] = m
        else:
            ss = _load_snowball_signal_series(name)   # Period 인덱스 월말 종가
            if not ss.empty:
                cols[name] = ss
    if not cols:
        return pd.DataFrame()
    px = pd.DataFrame(cols).sort_index()
    ret = (px / px.shift(1) - 1.0) * 100.0
    ret.index = ret.index.strftime('%Y-%m')
    return ret
