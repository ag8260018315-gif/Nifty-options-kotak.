"""What premium subscribes to, and how the tokens are found.

SENSEX is a BSE index. Its feed name defaults to 'bse_cm|SENSEX' and can be overridden with PREMIUM_SENSEX_SUBSCRIPTION
because the exact name must be confirmed on a live Kotak account (tools/probe_premium_symbols.py does that).
Stocks are NSE cash-market equities (a large-cap list; override with PREMIUM_STOCKS=SYM1,SYM2,...). Their feed tokens
come from Kotak's own nse_cm scrip master, so nothing is guessed. Anything that cannot be resolved is skipped and reported.
"""
import csv
import io
import logging
import os
from dataclasses import dataclass, field

import httpx

from lib.kotak_client import kotak_client
from lib.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_STOCKS = [
    # Nifty 50 style large caps
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK",
    "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "BAJFINANCE", "NESTLEIND", "WIPRO", "HCLTECH", "NTPC", "POWERGRID",
    "ONGC", "TATASTEEL", "M&M", "TECHM", "JSWSTEEL", "ADANIENT", "ADANIPORTS", "COALINDIA", "BAJAJFINSV", "DRREDDY", "CIPLA",
    "GRASIM", "HINDALCO", "BRITANNIA", "EICHERMOT", "APOLLOHOSP", "BPCL", "TATAMOTORS", "INDUSINDBK", "HEROMOTOCO", "DIVISLAB",
    "SBILIFE", "HDFCLIFE", "TRENT", "BEL", "SHRIRAMFIN", "BAJAJ-AUTO", "TATACONSUM",
    # Nifty Next 50 style
    "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "BANKBARODA", "BERGEPAINT", "BOSCHLTD", "CANBK", "CHOLAFIN", "COLPAL", "DLF", "DABUR",
    "GAIL", "GODREJCP", "HAVELLS", "ICICIGI", "ICICIPRULI", "INDIGO", "IOC", "IRCTC", "JINDALSTEL", "LICI", "LUPIN", "MARICO",
    "MUTHOOTFIN", "NAUKRI", "PFC", "PIDILITIND", "PNB", "RECLTD", "SIEMENS", "SRF", "TATAPOWER", "TORNTPHARM", "UNIONBANK", "VEDL",
    "ZYDUSLIFE", "HAL", "BHEL", "IDFCFIRSTB", "YESBANK", "MAXHEALTH", "POLYCAB", "ABB", "TVSMOTOR", "CGPOWER", "PERSISTENT", "LTIM",
    "MPHASIS", "COFORGE", "PAGEIND", "ASHOKLEY", "BALKRISIND", "BANDHANBNK", "FEDERALBNK", "AUBANK", "IDEA", "NMDC", "SAIL", "NHPC",
    "OFSS", "INDHOTEL", "JUBLFOOD", "MRF", "UPL", "ACC", "ALKEM", "AUROPHARMA", "BIOCON", "CUMMINSIND", "GMRAIRPORT", "HINDPETRO",
    "IGL", "LODHA", "OBEROIRLTY", "PETRONET", "PIIND", "TIINDIA", "VOLTAS",
]
INDEX_NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "BANK NIFTY", "FINNIFTY": "FIN NIFTY", "SENSEX": "SENSEX"}


def stock_symbols() -> list[str]:
    raw = os.environ.get("PREMIUM_STOCKS", "")
    items = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return items or list(DEFAULT_STOCKS)


def static_universe() -> tuple[dict[str, str], dict[str, str]]:
    """(names, kinds) for every premium instrument, known without any feed or login, so lists are never empty."""
    names = {sym: name for sym, name in INDEX_NAMES.items()}
    kinds = {sym: "index" for sym in INDEX_NAMES}
    for sym in stock_symbols():
        from premium.stockinfo import name_of

        names[sym], kinds[sym] = name_of(sym), "stock"
    return names, kinds


@dataclass
class PremiumPlan:
    index_tokens: list[str] = field(default_factory=list)  # extra index subscriptions, e.g. 'bse_cm|SENSEX'
    scrip_tokens: list[str] = field(default_factory=list)  # 'nse_cm|<token>'
    symbol_by_key: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    error: str | None = None


def parse_equities(csv_text: str, wanted: list[str]) -> dict[str, dict[str, str]]:
    """symbol -> {token, trading_symbol} for cash-market equities, from a Kotak nse_cm scrip master CSV."""
    found: dict[str, dict[str, str]] = {}
    wanted_set = set(wanted)
    for raw in csv.DictReader(io.StringIO(csv_text)):
        row = {key.strip().rstrip(";"): (value or "").strip() for key, value in raw.items() if key}
        name = row.get("pSymbolName", "").upper()
        trading = row.get("pTrdSymbol", "")
        if name not in wanted_set or name in found:
            continue
        if row.get("pGroup", "EQ") not in {"EQ", ""} and not trading.upper().endswith("-EQ"):
            continue
        token = row.get("pSymbol", "")
        if token:
            found[name] = {"token": token, "trading_symbol": trading}
    return found


async def build_plan() -> PremiumPlan:
    """Never raises: a premium problem must not disturb the NIFTY feed. Problems are reported in `error`."""
    plan = PremiumPlan()
    if os.environ.get("PREMIUM_FEED", "on").lower() in {"off", "0", "false", "no"}:
        plan.error = "Premium feed is switched off (PREMIUM_FEED=off)."
        return plan
    sensex = os.environ.get("PREMIUM_SENSEX_SUBSCRIPTION", "bse_cm|SENSEX")
    plan.index_tokens = [sensex]
    plan.symbol_by_key[sensex] = "SENSEX"
    plan.symbol_by_key[sensex.upper()] = "SENSEX"
    for sym, name in INDEX_NAMES.items():
        plan.names[sym], plan.kinds[sym] = name, "index"
    wanted = stock_symbols()
    try:
        response = await kotak_client.authenticated_get(settings.scrip_master_path)
        payload = response.get("data", response)
        paths = payload.get("filesPaths", []) if isinstance(payload, dict) else []
        url = next((p for p in paths if isinstance(p, str) and p.rsplit("/", 1)[-1].startswith("nse_cm")), None)
        if not url:
            raise RuntimeError("scrip master has no nse_cm file")
        async with httpx.AsyncClient(timeout=45) as client:
            text = (await _get(client, url))
        found = parse_equities(text, wanted)
    except Exception as exc:  # noqa: BLE001
        plan.error = f"stock tokens unavailable: {type(exc).__name__}"
        plan.unresolved = wanted
        logger.warning("PREMIUM_PLAN_ERROR kind=%s", type(exc).__name__)
        return plan
    for sym in wanted:
        info = found.get(sym)
        if not info:
            plan.unresolved.append(sym)
            continue
        key = f"nse_cm|{info['token']}"
        plan.scrip_tokens.append(key)
        plan.symbol_by_key[key] = sym
        from premium.stockinfo import name_of

        plan.names[sym], plan.kinds[sym] = name_of(sym), "stock"
    logger.info("PREMIUM_PLAN stocks=%s unresolved=%s", len(plan.scrip_tokens), len(plan.unresolved))
    return plan


async def _get(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text
