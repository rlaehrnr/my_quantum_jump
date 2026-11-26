"""배분 입력, 이번 달 현황과 확정월 분석의 공통 화면."""
import math

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

from utils.snowball_allocation import portfolio_stats
from utils.three_strategy import (
    Allocation, DEFAULT_ALLOCATION, LEG_LABELS, LEGS, SNOW, VERIFIED_HISTORY_END, backtest_window,
    combine, current_month, ratio_part, ratio_table, schedule_table, seasonal_tables,
)
from utils.three_strategy_live import KOSPI_ENSEMBLE_COLUMN, extend_history, kospi_results, snowball_current
from utils.three_strategy_preferences import PAGE, current_allocation, save_preferences, share_url
from utils.three_strategy_store import HISTORY_TAB, load_history


OUTER_LABELS = ("코스피200", "스노우볼", "소형주 퀀트")
INNER_LABELS = tuple(LEG_LABELS[key] for key in SNOW)
PCT = st.column_config.NumberColumn(format="percent")


def percent(value):
    return f"{value:+.2%}" if value is not None and pd.notna(value) and math.isfinite(value) else "—"


def _history():
    last = str(pd.Period(current_month(), freq="M")-1)
    history = load_history()
    return extend_history(history, last), last


def _format(table, columns):
    return {key: PCT for key in columns if key in table.columns}


def _display(df, percentages=(), **options):
    table = df.data if isinstance(df, Styler) else df
    st.dataframe(df, width="stretch", column_config=_format(table, percentages), **options)


def _heatmap_color(value):
    if pd.isna(value) or value == 0:
        return ""
    color = "239, 68, 68" if value < 0 else "22, 163, 74"
    return f"background-color: rgba({color}, {min(abs(value)*4, .6):.2f})"


def _weighted_current(values, amounts, keys):
    selected = [key for key in keys if amounts.get(key, 0) > 0]
    if not selected or any(key not in values or pd.isna(values[key]) for key in selected):
        return None
    denominator = sum(amounts[k] for k in selected)
    return sum(values[k]*amounts[k] for k in selected)/denominator


def _current_section(month, amounts, history, *, show_components=False):
    # One data source failing does not hide the other strategies or the backtest.
    values, details = {}, {}
    try:
        k = kospi_results()
        if month in k.index and KOSPI_ENSEMBLE_COLUMN in k:
            values["kospi"] = float(k.at[month, KOSPI_ENSEMBLE_COLUMN])/100
            details["kospi"] = str(k.at[month, "중지 사유"] or "주식 보유")
    except Exception:
        pass
    returns = {}
    try:
        returns = snowball_current(month)
    except Exception:
        pass
    for name, info in returns.items():
        if "krw" in info:
            values[name] = info["krw"]
    if month in history.index and pd.notna(history.at[month, "small"]):
        values["small"] = history.at[month, "small"]
    total = _weighted_current(values, amounts, LEGS)
    snow = _weighted_current(values, amounts, SNOW)
    for column, (name, value) in zip(st.columns(4), [
        ("3전략 종합", total), ("코스피200", values.get("kospi")),
        ("스노우볼", snow), ("소형주 퀀트", values.get("small")),
    ]):
        column.metric(name, percent(value))
    st.caption("월중 잠정 · 코스피 운영 아카이브, 스노우볼 일봉·환율, 소형주 시트 수익률 기준")
    missing = [LEG_LABELS[k] for k in LEGS if amounts[k] > 0 and k not in values]
    if missing:
        st.caption("종합에 필요한 수익률 대기 · " + ", ".join(missing))
    if show_components:
        rows = []
        for key, info in returns.items():
            rows.append({"전략": LEG_LABELS[key], "보유": info["hold"], "국면": info["mode"],
                         "종가일": info.get("date", ""), "원화 월중": info.get("krw"),
                         "현지통화 월중": info.get("local")})
        if rows:
            _display(pd.DataFrame(rows), ["원화 월중", "현지통화 월중"], hide_index=True)
        if "kospi" in details:
            st.caption(f"코스피200 · {details['kospi']}")


def _windows(history, last):
    return {key: backtest_window(history, LEGS, last, common=common, verified_end=VERIFIED_HISTORY_END)
            for key, common in [("장기 · 이력 미가용분 현금", False), ("공통 · 6개 구성 이력", True)]}


def _results(windows, amounts):
    output = {}
    for name, frame in windows.items():
        if frame.empty:
            continue
        result = portfolio_stats(combine(frame, amounts))
        result["start"], result["end"] = frame.index[[0, -1]]
        output[name] = result
    return output


def _headline(results):
    for label, r in results.items():
        st.caption(f"{label} · {r['start']}~{r['end']} · {r['n']}개월")
        for c, (key, value) in zip(st.columns(4), [
            ("연복리", percent(r["cagr"]) if r["n"] >= 12 else "—"), ("월말 MDD", percent(r["mdd"])),
            ("소르티노", f"{r['sortino']:.2f}" if math.isfinite(r["sortino"]) else "—"), ("승률", percent(r["win"])),
        ]):
            c.metric(key, value)


def _custom_plan(amounts):
    pair_total = amounts["kospi"] + amounts["meritz"]
    if not pair_total:
        return None
    with st.expander("코스피200과 또 메리츠 사이 비중 이동 비교"):
        enabled = st.checkbox("비교 배분 추가", key="three_compare_enabled")
        st.caption("전체 기준에서 코스피200과 또 메리츠의 합계, 나머지 네 구성의 비중을 유지합니다.")
        if enabled:
            meritz = st.number_input("비교할 또 메리츠 비율", min_value=0.0, max_value=float(pair_total),
                                     value=float(amounts["meritz"]), step=1.0, key="three_compare_meritz")
            return amounts | {"kospi": pair_total-meritz, "meritz": meritz}
    return None


def _allocation_summary(allocation):
    total = sum(allocation.outer)
    st.markdown(" · ".join(f"**{label} {ratio_part(part)}** ({part/total:.2%})"
                           for label, part in zip(OUTER_LABELS, allocation.outer)))
    st.caption("스노우볼 내부 · " + " / ".join(f"{label} {ratio_part(part)}"
                                              for label, part in zip(INNER_LABELS, allocation.inner)))


@st.fragment(run_every="60s")
def dashboard_allocation():
    month = current_month()
    st.subheader("3전략 조합")
    allocation = current_allocation()
    amounts = allocation.weights()
    _allocation_summary(allocation)
    st.page_link(PAGE, label="비율 수정 및 상세 분석")
    try:
        history, last = _history()
    except ValueError as exc:
        st.warning(str(exc))
        return
    except Exception:
        st.warning("종합 배분 자료를 불러오지 못했습니다.")
        return
    windows = _windows(history, last)
    chosen = next((name for name, rows in windows.items() if not rows.empty), None)
    if chosen is not None:
        _headline(_results({chosen: windows[chosen]}, amounts))
    st.caption(f"{month} 월중 수익률")
    _current_section(month, amounts, history)


@st.fragment(run_every="60s")
def _report(month, amounts):
    try:
        history, last = _history()
    except ValueError as exc:
        st.warning(str(exc))
        return
    except Exception:
        st.warning("구글 시트에서 분석 자료를 읽지 못했습니다.")
        return
    windows = _windows(history, last)
    results = _results(windows, amounts)
    _headline(results)
    plan = _custom_plan(amounts)
    overview, live, season, schedule, optimizer = st.tabs(
        ["백테스트", "이번 달", "계절성", "리밸런싱", "비중 비교"])
    alternatives = _results(windows, plan) if plan else {}
    with live:
        _current_section(month, amounts, history, show_components=True)
        st.caption(f"소형주의 월 수익률은 구글 시트 {HISTORY_TAB} 탭의 소형주 열에서 읽습니다.")
    with overview:
        st.caption("매월 목표 비중을 복원한 기준 성과입니다. 전략 간 이동 비용은 리밸런싱 탭에서 적용할 수 있습니다.")
        if not results:
            st.info("확정 월수익 자료가 필요합니다.")
        else:
            name = st.selectbox("상세 기간", tuple(results), key="three_summary_span")
            p = results[name]
            series = {"저장 배분": p}
            if name in alternatives:
                series["비교 배분"] = alternatives[name]
            st.line_chart(pd.DataFrame({label: value["equity"] for label, value in series.items()}), y_label="자산 배수")
            st.line_chart(pd.DataFrame({label: value["dd"] for label, value in series.items()}), y_label="월말 낙폭")
            for label, value in series.items():
                events = pd.DataFrame(sorted(value["periods"], key=lambda e: e["mdd"])[:10]).rename(columns={
                    "peak":"고점", "trough":"저점", "recovered":"회복", "months":"경과 개월", "mdd":"낙폭"})
                if not events.empty:
                    st.markdown(f"**{label} · 월말 MDD 상위 10건 · {value['start']}~{value['end']}**")
                    _display(events, ["낙폭"], hide_index=True)
            _display(pd.DataFrame({"월 수익률":p["ret"], "월말 낙폭":p["dd"]}), ["월 수익률","월말 낙폭"])
    with season:
        enough = [key for key, r in results.items() if r["n"] >= 12]
        if not enough:
            st.info("계절성 표를 만들 확정월 자료가 부족합니다.")
        else:
            name = st.selectbox("계절성 기간", enough, key="three_season_span")
            selected = results[name]
            if name in alternatives:
                target = st.radio("계절성 배분", ("저장 배분", "비교 배분"), horizontal=True)
                if target == "비교 배분":
                    selected = alternatives[name]
            st.caption(f"{selected['start']}~{selected['end']} · {selected['n']}개월")
            m, q, half, heat, cycle = seasonal_tables(selected["ret"])
            for label, t in [("월별", m), ("분기별", q), ("반기 · 미국 중간선거해", half)]:
                st.markdown(f"**{label}**")
                _display(t, ["평균", "중앙값", "승률"])
            st.markdown("**월별 히트맵**")
            _display(heat.style.format("{:+.2%}", na_rep="·").map(_heatmap_color))
            with st.expander("미국 대통령 8년 주기 · 표본·평균·승률"):
                _display(cycle, ["평균", "중앙값", "승률"])
    with schedule:
        if results:
            name = st.selectbox("리밸런싱 비교 기간", tuple(results), key="three_schedule_span")
            mode = st.radio("조정 범위", ("코스피200·또 메리츠만", "전체 목표비중"), horizontal=True,
                            key="three_rebalance_mode")
            cost = st.select_slider("전략 간 편도 비용", [0., .001, .0025, .005], value=.0025,
                                    format_func=lambda v: f"{v:.2%}", key="three_rebalance_fee")
            st.caption("해당 월 수익 반영 후 조정합니다. 두 전략만 선택하면 나머지 평가액은 각 전략에서 굴러갑니다.")
            pair_only = mode.startswith("코스피")
            r = results[name]
            st.caption(f"{r['start']}~{r['end']} · {r['n']}개월 · 소르티노 내림차순")
            schedules = schedule_table(windows[name], amounts, fee=cost, pair_only=pair_only)
            percentage_columns = ["연복리", "월말 MDD"]
            if plan:
                alt_schedule = schedule_table(windows[name], plan, fee=cost, pair_only=pair_only)
                schedules = schedules.merge(alt_schedule, on=["빈도", "조정 월말"], suffixes=("", " (비교)"))
                percentage_columns += ["연복리 (비교)", "월말 MDD (비교)"]
            _display(schedules, percentage_columns, hide_index=True)
    with optimizer:
        if results:
            name = st.selectbox("비중 비교 기간", tuple(results), key="three_optimizer_span")
            if plan:
                options = []
                for label, weights in (("저장 배분", amounts), ("비교 배분", plan)):
                    r = portfolio_stats(combine(windows[name], weights))
                    options.append({
                        "배분": label, "코스피200": weights["kospi"]/sum(weights.values()),
                        "스노우볼": sum(weights[key] for key in SNOW)/sum(weights.values()),
                        "소형주": weights["small"]/sum(weights.values()),
                        "또 메리츠": weights["meritz"]/sum(weights.values()),
                        "연복리": r["cagr"], "월말 MDD": r["mdd"], "소르티노": r["sortino"],
                        "월 승률": r["win"],
                    })
                _display(pd.DataFrame(options), ["코스피200", "스노우볼", "소형주", "또 메리츠",
                                                 "연복리", "월말 MDD", "월 승률"], hide_index=True)
            mode = st.radio("배분 후보", ("코스피200·또 메리츠 사이만", "3전략 전체 10% 단위 (66개)"),
                            horizontal=True, key="three_optimizer_mode")
            pair_only = mode.startswith("코스피")
            candidate_base = amounts
            if pair_only:
                st.caption("두 전략의 비중 합계를 1% 간격으로 나눕니다.")
            else:
                internal = st.selectbox("스노우볼 내부 구성", ("저장한 비중", "4전략 균등", "또 메리츠 단독"))
                if internal != "저장한 비중":
                    candidate_base = amounts | dict.fromkeys(SNOW, int(internal == "4전략 균등")) | {"meritz": 1}
                st.caption("비율 표기 순서 · 코스피200 / 스노우볼 / 소형주")
            st.caption("전략 내부 비용 반영 · 전략 간 이동 비용 0%")
            _display(ratio_table(windows[name], candidate_base, pair_only=pair_only),
                     ["코스피200","스노우볼","소형주","또 메리츠","연복리","월말 MDD"], hide_index=True)


def render_combination():
    st.title("3전략 조합")
    allocation = current_allocation()
    _allocation_summary(allocation)
    with st.expander("비율 수정"):
        with st.form(f"three_ratio_form_{allocation.encode()}"):
            st.caption("전체 배분 비율")
            outer = tuple(col.number_input(label, min_value=0.0, value=float(part), step=1.0)
                          for col, label, part in zip(st.columns(3), OUTER_LABELS, allocation.outer))
            st.caption("스노우볼 내부 배분 비율")
            inner = tuple(col.number_input(label, min_value=0.0, value=float(part), step=1.0)
                          for col, label, part in zip(st.columns(4), INNER_LABELS, allocation.inner))
            save = st.form_submit_button("비율 저장", type="primary")
            reset = st.form_submit_button("기본 비율 복원")
        if save or reset:
            try:
                edited = DEFAULT_ALLOCATION if reset else Allocation(outer, inner)
            except ValueError as exc:
                st.error(str(exc))
            else:
                save_preferences(edited)
                st.rerun()
        url = share_url(allocation)
        if url:
            st.caption("이 브라우저에 비율을 저장합니다. 다른 기기에서는 이 링크를 열면 같은 비율을 적용합니다.")
            st.code(url, language=None)
    _report(current_month(), allocation.weights())
