from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


@dataclass(frozen=True)
class Asset:
    group: str
    label: str
    ticker: str
    weight: float

    @property
    def key(self):
        return self.ticker or self.label


KR_WINTER = (
    Asset("선진국 주식", "KODEX 200", "069500", 15),
    Asset("선진국 주식", "KODEX 미국S&P500에너지(합성)", "218420", 3),
    Asset("선진국 주식", "ACE 미국대형가치주액티브", "0127M0", 4),
    Asset("선진국 주식", "KODEX 미국나스닥100", "379810", 8),
    Asset("개도국 주식", "KODEX 차이나CSI300", "283580", 10),
    Asset("개도국 주식", "TIGER 차이나항셍테크", "371160", 5),
    Asset("개도국 주식", "TIGER 인도니프티50", "453870", 5),
    Asset("채권", "RISE KIS국고채30년Enhanced", "385560", 12.5),
    Asset("채권", "ACE 미국30년국채액티브", "476760", 12.5),
    Asset("실물자산", "ACE KRX금현물", "411060", 15),
    Asset("실물자산", "TIGER 은액티브", "0189B0", 5),
    Asset("실물자산", "TIGER 구리실물", "160580", 5),
)
KR_SUMMER = (
    Asset("선진국 주식", "KODEX 200", "069500", 10),
    Asset("선진국 주식", "KODEX 미국S&P500에너지(합성)", "218420", 2),
    Asset("선진국 주식", "ACE 미국대형가치주액티브", "0127M0", 3),
    Asset("선진국 주식", "KODEX 미국나스닥100", "379810", 5),
    Asset("개도국 주식", "KODEX 차이나CSI300", "283580", 5),
    Asset("개도국 주식", "KODEX 차이나항셍테크", "372330", 2),
    Asset("개도국 주식", "TIGER 인도니프티50", "453870", 3),
    Asset("채권", "RISE KIS국고채30년Enhanced", "385560", 10),
    Asset("채권", "PLUS 미국채30년액티브", "464470", 10),
    Asset("실물자산", "ACE KRX금현물", "411060", 14),
    Asset("실물자산", "TIGER 은액티브", "0189B0", 3),
    Asset("실물자산", "TIGER 구리실물", "160580", 3),
    Asset("현금", "현금", "", 30),
)
US_WINTER = (
    Asset("선진국 주식", "한국 주식 (EWY / FLKR)", "EWY", 10),
    Asset("선진국 주식", "미국 에너지 주식", "XLE", 3),
    Asset("선진국 주식", "미국 성장주 (QQQ / QQQM)", "QQQ", 9),
    Asset("선진국 주식", "미국 배당주", "SCHD", 4),
    Asset("선진국 주식", "폴란드 주식", "EPOL", 4),
    Asset("개도국 주식", "중국 주식", "ASHR", 7),
    Asset("개도국 주식", "중국 주식", "FXI", 3),
    Asset("개도국 주식", "칠레 주식", "ECH", 3),
    Asset("개도국 주식", "브라질 주식 (EWZ / FLBR)", "EWZ", 4),
    Asset("개도국 주식", "인도네시아 주식", "EIDO", 3),
    Asset("채권", "미국 채권 (TLT / VGLT)", "TLT", 15),
    Asset("채권", "GRVT", "", 10),
    Asset("실물자산", "금 (GLD / GLDM)", "GLD", 12),
    Asset("실물자산", "은 (SLV / SIVR)", "SLV", 4),
    Asset("실물자산", "구리 선물", "CPER", 4),
    Asset("실물자산", "종합원자재", "PDBC", 5),
)
US_SUMMER = (
    Asset("선진국 주식", "한국 주식", "EWY", 7),
    Asset("선진국 주식", "미국 에너지 주식", "XLE", 2),
    Asset("선진국 주식", "미국 성장주", "QQQ", 6),
    Asset("선진국 주식", "미국 배당주", "SCHD", 2),
    Asset("선진국 주식", "폴란드 주식", "EPOL", 3),
    Asset("개도국 주식", "중국 주식", "ASHR", 4),
    Asset("개도국 주식", "중국 주식", "FXI", 2),
    Asset("개도국 주식", "칠레 주식", "ECH", 2),
    Asset("개도국 주식", "브라질 주식 (EWZ / FLBR)", "EWZ", 2),
    Asset("채권", "미국 장기 국채", "TLT", 10),
    Asset("채권", "GRVT", "", 10),
    Asset("실물자산", "금", "GLD", 10),
    Asset("실물자산", "은", "SLV", 2.5),
    Asset("실물자산", "구리 선물", "CPER", 2.5),
    Asset("실물자산", "종합원자재", "PDBC", 5),
    Asset("현금", "현금", "", 30),
)
# "us"는 기존 저장 시트의 11~4월 행 식별자다.
PLANS = {"kr_winter": KR_WINTER, "kr_summer": KR_SUMMER, "us": US_WINTER, "us_summer": US_SUMMER}
MARKET_PLANS = {"kr": ("kr_winter", "kr_summer"), "us": ("us", "us_summer")}
BUDGET_HEADERS = {"원": "총 자산 (원)", "USD": "총 자산 (USD)"}
PLAN_VERSION = "2026-11-17-v2"
SHEET_TABS = {"kr": "한국", "us": "미국"}
SHEET_HEADER = ["배분표", "자산 ID", "자산군", "ETF/전략", "선택 종목코드", "목표 비중 (%)", "직접 입력 가격"]
ZERO = Decimal(0)


def decimal_value(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def default_rows(plan):
    return [
        {"asset": asset, "ticker": asset.ticker, "weight": asset.weight, "manual_price": None}
        for asset in PLANS[plan]
    ]


def valid_ticker(ticker, market):
    pattern = r"[A-Z0-9]{6}" if market == "kr" else r"[A-Z][A-Z0-9.-]{0,11}"
    return re.fullmatch(pattern, ticker) is not None


def plan_weights(rows):
    weights = [decimal_value(row["weight"]) for row in rows]
    if any(weight is None or not 0 <= weight <= 100 for weight in weights):
        return None
    return weights


@dataclass(frozen=True)
class Order:
    target: Decimal
    shares: int | None = None
    purchase: Decimal | None = None


@dataclass(frozen=True)
class Allocation:
    lines: list[Order]
    purchase_total: Decimal
    planned_cash: Decimal
    lot_remainder: Decimal
    pending: Decimal

    @property
    def cash_remaining(self):
        return self.planned_cash + self.lot_remainder + self.pending


def allocate(assets, rows, quotes):
    assets = decimal_value(assets)
    weights = plan_weights(rows)
    if assets is None or assets < 0 or weights is None or sum(weights) != 100:
        return None

    lines = []
    purchase_total = planned_cash = lot_remainder = pending = ZERO
    for row, weight in zip(rows, weights):
        target = assets * weight / 100
        asset = row["asset"]
        price = decimal_value(row["manual_price"]) or decimal_value(quotes.get(row["ticker"]))
        if asset.group == "현금":
            planned_cash += target
        elif not asset.ticker:
            purchase_total += target
            lines.append(Order(target, purchase=target))
            continue
        elif price is not None and price > 0:
            cost = price
            quantity = int(target // cost)
            purchase = quantity * cost
            purchase_total += purchase
            lot_remainder += target - purchase
            lines.append(Order(target, quantity, purchase))
            continue
        else:
            pending += target
        lines.append(Order(target))
    return Allocation(lines, purchase_total, planned_cash, lot_remainder, pending)


def read_settings(worksheet, plans):
    values = worksheet.get("A1:G40", value_render_option="UNFORMATTED_VALUE")
    rows = {plan: default_rows(plan) for plan in plans}
    if not values:
        return None, None, None, rows
    if len(values) < 2 or len(values[0]) < 3 or values[0][2] != "직접 입력 환율" or values[1] != SHEET_HEADER:
        raise ValueError("배분표 저장 형식이 다릅니다.")

    market = "us" if "us" in plans else "kr"
    allowed = ("원", "USD") if market == "us" else ("원",)
    currency = next((code for code in allowed if BUDGET_HEADERS[code] == values[0][0]), None)
    if currency is None:
        raise ValueError("저장된 총 자산 통화를 확인해 주세요.")
    current_version = values[0][4:6] == ["배분표 버전", PLAN_VERSION]
    budget = decimal_value(values[0][1])
    fx = decimal_value(values[0][3]) if len(values[0]) > 3 else None
    if (budget is not None and (budget < 0 or (currency == "원" and budget != int(budget)))) or (fx is not None and fx <= 0):
        raise ValueError("저장된 총 자산 또는 환율을 확인해 주세요.")
    saved = {}
    for line in values[2:]:
        if not any(line):
            continue
        if len(line) < 6 or line[0] not in rows or tuple(line[:2]) in saved:
            raise ValueError("저장된 배분표 행을 확인해 주세요.")
        saved[tuple(line[:2])] = line
    for plan, defaults in rows.items():
        for row in defaults:
            asset = row["asset"]
            line = saved.get((plan, asset.key))
            if line is None:
                continue
            ticker = str(line[4]).strip().upper()
            weight = decimal_value(line[5])
            price = decimal_value(line[6]) if len(line) > 6 else None
            if (asset.ticker and not valid_ticker(ticker, market)) or weight is None or not 0 <= weight <= 100:
                raise ValueError("저장된 종목코드 또는 목표 비중을 확인해 주세요.")
            row.update(ticker=ticker, weight=float(weight) if current_version else asset.weight, manual_price=float(price) if price and price > 0 else None)
    if budget is not None:
        budget = int(budget) if currency == "원" else float(budget)
    return budget, currency, float(fx) if fx is not None else None, rows


def write_settings(worksheet, budget, fx, plans):
    currency = "USD" if "us" in plans else "원"
    values = [[
        BUDGET_HEADERS[currency], "" if budget is None else budget, "직접 입력 환율",
        fx or "", "배분표 버전", PLAN_VERSION,
    ], SHEET_HEADER]
    for plan, rows in plans.items():
        for row in rows:
            asset = row["asset"]
            values.append([
                plan, asset.key, asset.group, asset.label, row["ticker"], row["weight"],
                row["manual_price"] or "",
            ])
    worksheet.update(values=values, range_name="A1", raw=True)
