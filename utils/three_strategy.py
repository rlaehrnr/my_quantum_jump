"""코스피200·스노우볼·소형주의 월별 배분 계산."""
from datetime import datetime, timedelta, timezone
from itertools import combinations_with_replacement
import math
import re

import numpy as np
import pandas as pd

from utils.portfolio_report import common_portfolio_months
from utils.snowball_allocation import portfolio_stats


LEG_LABELS = {
    "kospi": "코스피200", "meritz": "또 메리츠", "mam_isa": "맘 ISA",
    "ddo_pension": "또 연금", "sso_pension": "쏘 연금", "small": "소형주 퀀트",
}
LEGS = tuple(LEG_LABELS)
SNOW = LEGS[1:-1]
VERIFIED_HISTORY_END = "2026-10"
KST = timezone(timedelta(hours=9))
SCHEDULES = tuple(
    (label, tuple(range(offset, 13, step)))
    for label, step in (("매월", 1), ("분기", 3), ("연 2회", 6), ("연 1회", 12))
    for offset in range(1, step + 1)
)


def current_month():
    return str(pd.Period(datetime.now(KST).date(), freq="M"))


def month_key(value):
    value = str(value).strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("투자월은 YYYY-MM 형식이어야 합니다.")
    return value


def validate_amounts(amounts):
    if set(amounts) != set(LEGS):
        raise ValueError("여섯 전략의 금액을 모두 입력하세요. 미투자는 0을 입력하세요.")
    result = {}
    for key in LEGS:
        try:
            value = float(str(amounts[key]).strip().replace(",", ""))
        except ValueError:
            value = math.nan
        if not math.isfinite(value) or not 0 <= value <= 2**53 - 1:
            raise ValueError(f"{LEG_LABELS[key]} 금액은 0 이상의 유효한 숫자여야 합니다.")
        result[key] = value
    if not sum(result.values()):
        raise ValueError("투자금 합계는 0보다 커야 합니다.")
    return result


def parse_history(rows):
    decoded = {}
    for row in rows:
        if not row or not str(row[0]).strip():
            continue
        month = month_key(row[0])
        if month in decoded:
            raise ValueError(f"월 수익률에 중복 투자월이 있습니다. {month}")
        values = []
        for key, cell in zip(LEGS, list(row[1:7]) + [""] * len(LEGS)):
            text = str(cell if cell is not None else "").strip()
            if not text:
                values.append(np.nan)
                continue
            try:
                val = float(text.rstrip("%").replace(",", ""))
                if text.endswith("%"):
                    val /= 100
            except ValueError:
                val = np.nan
            if not math.isfinite(val) or val < -1:
                raise ValueError(f"{month} {LEG_LABELS[key]} 수익률을 확인하세요.")
            values.append(val)
        decoded[month] = values
    frame = pd.DataFrame.from_dict(decoded, orient="index", columns=LEGS, dtype=float).sort_index()
    return frame


def backtest_window(history, selected, last_closed, *, common, verified_end=None):
    frame = history.loc[history.index <= last_closed].dropna(how="all")
    if frame.empty:
        return frame
    calendar = pd.period_range(frame.index[0], frame.index[-1], freq="M").astype(str)
    frame = frame.reindex(calendar)
    if common:
        return frame.loc[common_portfolio_months(frame, selected)]
    available = frame[list(selected)].notna()
    internal_gap = (available.cummax() & ~available).any(axis=1) | ~available.any(axis=1)
    if verified_end:
        # 과거 검증 원장의 산발적 미운용 월은 기존 보고서와 같이 현금이다.
        # 운영 시작 후에는 누락이 있는 달부터 확정 백테스트에 편입하지 않는다.
        internal_gap &= (frame.index > verified_end) | ~available.any(axis=1)
    if internal_gap.any():
        frame = frame.iloc[:np.flatnonzero(internal_gap.to_numpy())[0]]
    return frame


def combine(frame, amounts):
    weights = pd.Series(validate_amounts(amounts))
    return frame[list(LEGS)].fillna(0) @ (weights / weights.sum())


def schedule_returns(frame, amounts, months, *, fee, pair_only):
    target = np.array(list(validate_amounts(amounts).values()))
    target /= target.sum()
    units = target.copy()
    first_count = 2 if pair_only else len(LEGS)
    share = target[:first_count].sum()
    split = target[:first_count] / share if share else None
    results = []
    for i, (m, row) in enumerate(zip(frame.index, frame[list(LEGS)].fillna(0).to_numpy())):
        updated = units * (1 + row)
        if split is not None and i+1 < len(frame) and int(m[-2:]) in months:
            gross = updated[:first_count].sum()
            net = gross
            for _ in range(8):
                net = gross - fee * np.abs(split * net - updated[:first_count]).sum()
            updated[:first_count] = split * net
        balance = updated.sum()
        results.append(balance - 1)
        units = updated / balance if balance > 0 else target
    return pd.Series(results, index=frame.index)


def schedule_table(frame, amounts, *, fee, pair_only):
    rows = []
    for name, months in SCHEDULES:
        value = portfolio_stats(schedule_returns(frame, amounts, months, fee=fee, pair_only=pair_only))
        rows.append({
            "빈도": name, "조정 월말": "·".join(map(str, months)) if len(months)<12 else "매월",
            "연복리": value["cagr"], "월말 MDD": value["mdd"], "소르티노": value["sortino"],
        })
    return pd.DataFrame(rows).sort_values("소르티노", ascending=False)


def ratio_table(frame, amounts, *, pair_only):
    amounts = validate_amounts(amounts)
    plans = []
    if pair_only:
        total = amounts["kospi"]+amounts["meritz"]
        for pct in range(101):
            plans.append(amounts | {"kospi": total*pct/100, "meritz": total*(100-pct)/100})
        plans.append(amounts)
    else:
        snow_total = sum(amounts[key] for key in SNOW)
        internal = {key: amounts[key]/snow_total if snow_total else 1/len(SNOW) for key in SNOW}
        for i,j in combinations_with_replacement(range(11), 2):
            plans.append({"kospi":i, "small":10-j, **{key:(j-i)*rate for key,rate in internal.items()}})
    rows = []
    for plan in plans:
        a = portfolio_stats(combine(frame, plan))
        total = sum(plan.values())
        rows.append({
            "코스피200": plan["kospi"]/total, "스노우볼": sum(plan[k] for k in SNOW)/total,
            "소형주": plan["small"]/total, "또 메리츠": plan["meritz"]/total,
            "연복리": a["cagr"], "월말 MDD": a["mdd"], "소르티노": a["sortino"],
        })
    return pd.DataFrame(rows).drop_duplicates().sort_values("소르티노", ascending=False)


def seasonal_tables(series):
    periods = pd.PeriodIndex(series.index, freq="M")
    a = series.set_axis(periods)
    def summarize(s):
        return pd.Series({"표본":len(s),"평균":s.mean(),"중앙값":s.median(),"승률":(s>0).mean()})
    def bins(labels):
        groups = a.groupby(labels)
        return pd.Series({k:(1+s).prod()-1 for k,s in groups if len(s)==6})
    annual = (1+a).groupby(periods.year).prod()-1
    months = a.groupby(periods.month).apply(summarize).unstack().rename_axis("월")
    quarters = (1+a).groupby(periods.asfreq("Q")).agg(lambda s:s.prod()-1 if len(s)==3 else np.nan).dropna()
    quarters = quarters.groupby(quarters.index.quarter).apply(summarize).unstack().rename_axis("분기")
    winter = (periods.month>=11)|(periods.month<=4)
    winter_series = bins([(y+(m>=11) if w else -1) for y,m,w in zip(periods.year,periods.month,winter)])
    summer_series = bins([(y if not w else -1) for y,w in zip(periods.year,winter)])
    winter_series = winter_series.drop(-1, errors="ignore")
    summer_series = summer_series.drop(-1, errors="ignore")
    midterm = (summer_series.index-2022)%4==0
    calendar = pd.DataFrame({"연도":periods.year, "월":periods.month,"수익률":a.to_numpy()})
    heatmap = calendar.pivot(index="연도", columns="월", values="수익률").reindex(columns=range(1,13))
    heatmap = heatmap.rename(columns=lambda month: f"{month}월")
    heatmap["연도 누적"] = annual
    half_years = pd.DataFrame({
        "11~4월": summarize(winter_series), "5~10월": summarize(summer_series),
        "중간선거해 5~10월": summarize(summer_series[midterm]), "그 외 5~10월": summarize(summer_series[~midterm]),
    }).T
    cycle = calendar.assign(연차=(calendar["연도"]-2021)%8+1)
    cycle = cycle.groupby(["연차","월"])["수익률"].apply(summarize).unstack()
    return months, quarters, half_years, heatmap, cycle
