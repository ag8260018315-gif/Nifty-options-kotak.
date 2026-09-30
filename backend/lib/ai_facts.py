"""Grounding helpers for the AI analyst.

The server computes every number. The model only gets named facts, and anything it writes is checked:
every number must match a fact (within rounding), and advice wording is rejected. Nothing here calls the model.
"""
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

RULE_STATES = {
    "BUY CALLS": "bullish alignment (PCR bullish and price rising over 5 and 15 minutes)",
    "BUY PUTS": "bearish alignment (PCR bearish and price falling over 5 and 15 minutes)",
    "WAIT": "no alignment",
}

# Wording that turns description into advice. Checked case-insensitively on whole words.
ADVICE_PATTERNS = [
    r"\bbuy(?:ing)?\b",
    r"\bsell(?:ing)?\b",
    r"\bstop[\s-]?loss(?:es)?\b",
    r"\btargets?\b",
    r"\bgo(?:ing)?\s+(?:long|short)\b",
    r"\bbook(?:ing)?\s+(?:profits?|loss(?:es)?)\b",
    r"\b(?:should|must|consider)\s+(?:enter|exit|trade|take|add)\b",
    r"\bentry\s+(?:point|level|price)\b",
    r"\bexit\s+(?:point|level|price)\b",
    r"\bguarantee[sd]?\b",
    r"\bwill\s+(?:rise|fall|go\s+up|go\s+down|reach|hit|touch)\b",
]
_ADVICE = [re.compile(pattern, re.IGNORECASE) for pattern in ADVICE_PATTERNS]
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_DATE = re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})[a-z]*\.?\s+\d{{2,4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.(\d+))?(?:\s*(lakh|lakhs|crore|crores|cr|k)\b)?", re.IGNORECASE)
_SCALE = {"lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _clock(value: datetime | None) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).strftime("%H:%M:%S")


def build_facts(snapshot: Any, plan: dict[str, Any] | None) -> dict[str, Any]:
    """Named facts for the prompt. Missing values are left out, never filled in."""
    facts: dict[str, Any] = {}

    def put(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, float):
            value = round(value, 6)  # gamma is ~0.0008, so 4 decimals would distort it
        facts[key] = value

    spot = snapshot.spot
    structure = snapshot.structure
    put("index", snapshot.symbol)
    put("expiry", snapshot.expiry)
    put("feed_state", snapshot.feed.state)
    put("data_source", getattr(snapshot.feed, "source", None))
    put("data_time_ist", _clock(snapshot.feed.last_tick or spot.timestamp))
    if spot.ltp and spot.ltp > 0:
        put("spot", spot.ltp)
        put("change_points", spot.change)
        put("change_percent", spot.pct_change)
        put("day_high", spot.high or None)
        put("day_low", spot.low or None)
        put("day_open", getattr(spot, "open", None))
        put("previous_close", getattr(spot, "prev_close", None))
    chain = sorted(snapshot.option_chain, key=lambda row: row.strike)
    if chain:
        put("pcr", structure.pcr)
        start = getattr(structure, "pcr_start", None)
        if start is not None:
            put("pcr_at_first_update", start)
            put("pcr_change_today", round(structure.pcr - start, 2))
        put("max_pain", structure.max_pain)
        put("call_oi_total_window", getattr(structure, "total_call_oi", None) or sum(row.call.oi for row in chain))
        put("put_oi_total_window", getattr(structure, "total_put_oi", None) or sum(row.put.oi for row in chain))
        put("strikes_in_window", len(chain))
        for rank, row in enumerate(sorted(chain, key=lambda item: item.call.oi, reverse=True)[:3], start=1):
            put(f"call_oi_rank{rank}_strike", row.strike)
            put(f"call_oi_rank{rank}", row.call.oi)
        for rank, row in enumerate(sorted(chain, key=lambda item: item.put.oi, reverse=True)[:3], start=1):
            put(f"put_oi_rank{rank}_strike", row.strike)
            put(f"put_oi_rank{rank}", row.put.oi)
        legs = [(row.strike, "call", row.call.oi_change) for row in chain] + [(row.strike, "put", row.put.oi_change) for row in chain]
        added = max(legs, key=lambda item: item[2])
        shed = min(legs, key=lambda item: item[2])
        if added[2] > 0:
            put("largest_oi_addition_strike", added[0])
            put("largest_oi_addition_side", added[1])
            put("largest_oi_addition", added[2])
        if shed[2] < 0:
            put("largest_oi_reduction_strike", shed[0])
            put("largest_oi_reduction_side", shed[1])
            put("largest_oi_reduction", shed[2])
        atm = next((row for row in chain if row.is_atm), None) or min(chain, key=lambda row: abs(row.strike - (spot.ltp or 0)))
        put("atm_strike", atm.strike)
        for side, leg in (("ce", atm.call), ("pe", atm.put)):
            put(f"atm_{side}_ltp", leg.ltp)
            put(f"atm_{side}_iv", leg.iv or None)
            put(f"atm_{side}_delta", leg.delta)
            put(f"atm_{side}_gamma", getattr(leg, "gamma", None))
            put(f"atm_{side}_theta_per_day", getattr(leg, "theta", None))
            put(f"atm_{side}_vega", getattr(leg, "vega", None))
        if atm.call.iv and atm.put.iv:
            put("atm_iv_gap_pe_minus_ce", round(atm.put.iv - atm.call.iv, 2))
    if plan and plan.get("available"):
        put("move_5m_points", plan.get("move_5m"))
        put("move_15m_points", plan.get("move_15m"))
        put("momentum", (plan.get("trend") or "").lower() or None)
        put("rule_state", RULE_STATES.get(plan.get("signal", "WAIT"), "no alignment"))
        put("range_15m_high", (plan.get("pe") or {}).get("index_stop"))
        put("range_15m_low", (plan.get("ce") or {}).get("index_stop"))
    return facts


def compact_rows(snapshot: Any, width: int = 5) -> list[list[float]]:
    """ATM ±width strikes as [strike, call_oi, call_oi_change, put_oi, put_oi_change]."""
    chain = sorted(snapshot.option_chain, key=lambda row: row.strike)
    if not chain:
        return []
    atm_index = next((i for i, row in enumerate(chain) if row.is_atm), len(chain) // 2)
    window = chain[max(0, atm_index - width): atm_index + width + 1]
    return [[row.strike, row.call.oi, row.call.oi_change, row.put.oi, row.put.oi_change] for row in window]


def _indian(value: float, decimals: int) -> str:
    """Indian digit grouping, as on the dashboard: 3,00,000 and 25,010.50."""
    sign = "-" if value < 0 else ""
    text = f"{abs(value):.{decimals}f}"
    whole, _, fraction = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}{'.' + fraction if fraction else ''}"


def _fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    return _indian(float(value), decimals)


def _signed(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "—"
    text = _fmt(value, decimals)
    return f"+{text}" if value > 0 else text


CARD_TITLES = {"oi": "OI insight", "pcr": "PCR insight", "volatility": "Volatility insight", "greeks": "Greek insight", "structure": "Market structure"}


def card_data(facts: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """The numbers each card shows. Rendered by the server, never by the model."""
    f = facts.get
    change_side = f("largest_oi_addition_side")
    return {
        "oi": [
            {"label": "Most call OI", "value": f"{_fmt(f('call_oi_rank1_strike'), 0)} ({_fmt(f('call_oi_rank1'), 0)})"},
            {"label": "Most put OI", "value": f"{_fmt(f('put_oi_rank1_strike'), 0)} ({_fmt(f('put_oi_rank1'), 0)})"},
            {"label": "Largest OI addition", "value": f"{_fmt(f('largest_oi_addition_strike'), 0)} {change_side.upper() if isinstance(change_side, str) else ''} ({_signed(f('largest_oi_addition'), 0)})".strip()},
        ],
        "pcr": [
            {"label": "PCR", "value": _fmt(f("pcr"))},
            {"label": "Change today", "value": _signed(f("pcr_change_today"))},
            {"label": "Call OI (window)", "value": _fmt(f("call_oi_total_window"), 0)},
            {"label": "Put OI (window)", "value": _fmt(f("put_oi_total_window"), 0)},
        ],
        "volatility": [
            {"label": "ATM CE IV", "value": f"{_fmt(f('atm_ce_iv'))}%" if f("atm_ce_iv") is not None else "—"},
            {"label": "ATM PE IV", "value": f"{_fmt(f('atm_pe_iv'))}%" if f("atm_pe_iv") is not None else "—"},
            {"label": "PE minus CE IV", "value": _signed(f("atm_iv_gap_pe_minus_ce"))},
        ],
        "greeks": [
            {"label": "ATM CE delta", "value": _fmt(f("atm_ce_delta"), 3)},
            {"label": "ATM PE delta", "value": _fmt(f("atm_pe_delta"), 3)},
            {"label": "ATM gamma", "value": _fmt(f("atm_ce_gamma"), 5)},
            {"label": "ATM CE theta / day", "value": _fmt(f("atm_ce_theta_per_day"))},
            {"label": "ATM vega", "value": _fmt(f("atm_ce_vega"))},
        ],
        "structure": [
            {"label": "Spot", "value": _fmt(f("spot"))},
            {"label": "Max pain", "value": _fmt(f("max_pain"), 0)},
            {"label": "ATM strike", "value": _fmt(f("atm_strike"), 0)},
            {"label": "5 min move", "value": _signed(f("move_5m_points"))},
            {"label": "15 min move", "value": _signed(f("move_15m_points"))},
        ],
    }


def allowed_numbers(facts: dict[str, Any], rows: list[list[float]]) -> list[float]:
    values: list[float] = []
    for value in facts.values():
        number = _num(value)
        if number is not None:
            values.append(number)
    for row in rows:
        values.extend(float(value) for value in row)
    derived: list[float] = []
    for value in values:
        derived.append(abs(value))
    return values + derived


def extract_numbers(text: str) -> list[tuple[str, float, float, int]]:
    """(as written, value, unit scale, decimals written). Dates and clock times are ignored."""
    cleaned = _DATE.sub(" ", _TIME.sub(" ", text))
    found: list[tuple[str, float, float, int]] = []
    for match in _NUMBER.finditer(cleaned):
        whole = match.group(0)
        numeric = re.match(r"[-+−]?\d[\d,]*(?:\.\d+)?", whole)
        if numeric is None:
            continue
        try:
            value = float(numeric.group(0).replace(",", "").replace("−", "-"))
        except ValueError:
            continue
        unit = match.group(2)
        scale = _SCALE[unit.lower()] if unit else 1.0
        found.append((whole.strip(), value * scale, scale, len(match.group(1) or "")))
    return found


def _matches(value: float, allowed: list[float], scale: float = 1.0, decimals: int = 0) -> bool:
    """A written number is accepted only if the data rounds to it at the precision it was written with.

    "25,010" matches 25010.35 (it rounds to 25,010) but not 25,050. "1.2 crore" matches anything from
    1.15 to 1.25 crore. The sign is ignored, because "fell by 9,000" describes -9000.
    """
    # Small whole numbers are time windows and counts ("5 minutes", "±10 strikes", "3 strikes").
    if scale == 1.0 and decimals == 0 and value == int(value) and 0 <= abs(value) <= 60:
        return True
    tolerance = 0.5 * (10 ** -decimals) * scale + 1e-6
    magnitude = abs(value)
    return any(abs(magnitude - abs(candidate)) <= tolerance for candidate in allowed)


def check_text(text: str, allowed: list[float]) -> dict[str, list[str]]:
    """Returns the problems found: numbers not in the data, and advice wording."""
    bad_numbers = [raw for raw, value, scale, decimals in extract_numbers(text) if not _matches(value, allowed, scale, decimals)]
    advice = sorted({match.group(0).lower() for pattern in _ADVICE for match in pattern.finditer(text)})
    return {"numbers": bad_numbers, "advice": advice}
