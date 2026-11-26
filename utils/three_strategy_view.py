"""배분 입력, 이번 달 현황과 확정월 분석의 공통 화면."""
import math

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

from utils.snowball_allocation import portfolio_stats
from utils.three_strategy import (
    LEG_LABELS, LEGS, SNOW, VERIFIED_HISTORY_END, backtest_window, combine, current_month, ratio_table,
    schedule_table, seasonal_tables,
)
from utils.three_strategy_live import KOSPI_ENSEMBLE_COLUMN, extend_history, kospi_results, snowball_current
from utils.three_strategy_store import (
    AMOUNT_TAB, HISTORY_TAB, PORTFOLIO_SHEET_URL, check_access, load_history, portfolio_sheet,
    read_amounts, save_amounts,
)


AUTH = "three_strategy_unlocked"
PAGE = "pages/0_3전략_조합.py"
PCT = st.column_config.NumberColumn(format="percent")


def percent(value):
    return f"{value:+.2%}" if value is not None and pd.notna(value) and math.isfinite(value) else "—"


def _access():
    if st.session_state.get(AUTH):
        return True
    st.caption("투자금액과 백테스트는 기존 구글 시트의 투자배분 탭에서 연동 암호를 확인해 열 수 있습니다.")
    st.link_button("구글 시트 열기", PORTFOLIO_SHEET_URL)
    with st.form("three_strategy_unlock", clear_on_submit=True):
        code = st.text_input("투자배분 탭 B1 연동 암호", type="password")
        enter = st.form_submit_button("열기")
    if enter:
        try:
            allowed = check_access(code)
        except Exception:
            st.warning("구글 시트 연결을 확인할 수 없습니다. 잠시 후 다시 시도해주세요.")
        else:
            if allowed:
                st.session_state[AUTH] = True
                st.rerun()
            st.error("연동 암호를 확인해주세요.")
    return False


def _read(month):
    return read_amounts(portfolio_sheet().worksheet(AMOUNT_TAB), month)


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
    with st.expander("또 메리츠 금액을 바꿔 비교"):
        enabled = st.checkbox("비교 배분 추가", key="three_compare_enabled")
        st.caption("코스피200과 또 메리츠 합계, 나머지 네 금액은 유지합니다. 비교값은 구글 시트에 저장되지 않습니다.")
        if enabled:
            meritz = st.number_input("비교할 또 메리츠 금액 (원)", min_value=0.0, max_value=float(pair_total),
                                     value=float(amounts["meritz"]), step=10000.0, key="three_compare_meritz")
            return amounts | {"kospi": pair_total-meritz, "meritz": meritz}
    return None


@st.fragment(run_every="60s")
def dashboard_allocation():
    month = current_month()
    st.subheader(f"{month} 종합 결과")
    st.page_link(PAGE, label="3전략 조합 · 투자금 설정")
    if not st.session_state.get(AUTH):
        st.caption("3전략 조합에서 연동을 열면 여기에도 이번 달 배분과 성과가 표시됩니다.")
        return
    try:
        amounts = _read(month)
        if not amounts:
            st.info("이달 투자금액을 입력하면 종합 성과가 표시됩니다.")
            return
        history, last = _history()
    except ValueError as exc:
        st.warning(str(exc))
        return
    except Exception:
        st.warning("종합 배분 자료를 불러오지 못했습니다.")
        return
    _current_section(month, amounts, history)
    st.caption("배분 · " + " / ".join(f"{name} {val/sum(amounts.values()):.1%}" for name, val in [
        ("코스피200", amounts["kospi"]), ("스노우볼", sum(amounts[key] for key in SNOW)),
        ("소형주", amounts["small"]),
    ]))
    windows = _windows(history, last)
    chosen = list(windows)[-1] if not list(windows.values())[-1].empty else list(windows)[0]
    _headline(_results({chosen: windows[chosen]}, amounts))


@st.fragment(run_every="60s")
def _report(month):
    try:
        amounts = _read(month)
        if not amounts:
            st.info("이달의 여섯 금액을 저장하면 분석을 시작합니다.")
            return
        history, last = _history()
    except ValueError as exc:
        st.warning(str(exc))
        return
    except Exception:
        st.warning("구글 시트에서 분석 자료를 읽지 못했습니다.")
        return
    st.subheader("저장된 배분")
    weights = pd.DataFrame(
        {"전략": list(LEG_LABELS.values()), "금액(원)": list(amounts.values()),
         "비중": [v/sum(amounts.values()) for v in amounts.values()]})
    _display(weights, ["비중"], hide_index=True)
    plan = _custom_plan(amounts)
    live, overview, season, schedule, optimizer = st.tabs(
        ["이번 달", "백테스트", "계절성", "리밸런싱", "비중 비교"])
    windows = _windows(history, last)
    results = _results(windows, amounts)
    alternatives = _results(windows, plan) if plan else {}
    with live:
        _current_section(month, amounts, history, show_components=True)
        st.caption(f"소형주의 월 수익률은 구글 시트 {HISTORY_TAB} 탭의 소형주 열에서 읽습니다.")
    with overview:
        st.caption("매월 목표 비중을 복원한 기준 성과입니다. 전략 간 이동 비용은 리밸런싱 탭에서 적용할 수 있습니다.")
        _headline(results)
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
                st.caption("두 전략의 가변 금액을 1% 간격으로 나눕니다.")
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
    st.caption("코스피200 · 스노우볼 · 소형주 퀀트")
    if not _access():
        return
    if st.button("잠그기", key="three_lock"):
        st.session_state.pop(AUTH, None)
        for key in list(st.session_state):
            if key.startswith("three_amount_"):
                del st.session_state[key]
        st.rerun()
    month = current_month()
    st.subheader(f"{month} 투자금액")
    st.link_button("투자배분 시트 열기", PORTFOLIO_SHEET_URL)
    revision = st.session_state.get("three_form_revision", 0)
    if st.button("시트에서 다시 읽기", key="three_refresh"):
        st.session_state["three_form_revision"] = revision+1
        load_history.clear()
        st.rerun()
    try:
        tab = portfolio_sheet().worksheet(AMOUNT_TAB)
        defaults = read_amounts(tab, month) or {}
    except ValueError as exc:
        st.warning(str(exc))
        defaults = {}
    except Exception:
        st.warning("투자배분 탭을 읽지 못했습니다. 시트 연결을 확인해주세요.")
        return
    st.caption("원 단위 · 미투자는 0 · 시트에서 직접 수정한 금액도 1분 이내에 결과에 반영됩니다.")
    with st.form(f"three_form_{month}_{revision}"):
        amounts = {}
        for col, key in zip([*st.columns(3), *st.columns(3)], LEGS):
            amounts[key] = col.text_input(f"{LEG_LABELS[key]} (원)",
                value=f"{defaults[key]:,.0f}" if key in defaults else "",
                key=f"three_amount_{key}_{month}_{revision}")
        save = st.form_submit_button("구글 시트에 저장", type="primary")
    if save:
        try:
            save_amounts(tab, month, amounts)
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("시트에 저장하지 못했습니다. 입력값은 이 화면에 남아 있습니다.")
        else:
            st.success("이번 달 금액을 저장했습니다.")
    _report(month)
