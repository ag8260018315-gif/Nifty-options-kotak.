"""Trader's Exchange rules: what a listing may say and how much one person may post or send. Pure functions, no I/O.

The Exchange is a notice board for SERVICES (courses, tools, data, mentoring). It is not a place for trading tips, calls, signals for sale,
portfolio management or promised returns, and no money moves through it. Listings are held for the owner's approval before anyone sees them.
"""
import re
import time
from collections import defaultdict, deque

from fastapi import HTTPException

CATEGORIES = {
    "education": "Education & training",
    "tools": "Tools & software",
    "data": "Data & charting",
    "mentoring": "Journaling & mentoring (education only)",
    "other": "Other services",
}
MAX_LISTINGS = 5            # live (pending or approved) listings per person
MAX_NEW_LISTINGS_DAY = 3
MAX_ENQUIRIES_DAY = 10
MAX_MESSAGES_HOUR = 30
MAX_THREAD_MESSAGES = 100
REPORTS_TO_HIDE = 3         # this many different people reporting a listing hides it until the owner has looked
TITLE, DESC, PRICE, MSG, REASON, NAME = (5, 80), (30, 1000), 40, 600, 300, (3, 24)

RULES = [
    "Services only: courses, tools, data, charting help, mentoring about how markets work.",
    "No trading tips, calls, signals for sale, portfolio management, investment advice or promised or guaranteed returns.",
    "No money is handled here. Agree terms yourselves and be careful: check who you are dealing with before you pay anyone.",
    "Keep contact inside the Exchange: no phone numbers, emails, chat handles or links in a listing.",
    "Every listing is checked by the owner before it appears. Listings can be removed at any time.",
]

# Wording that marks an advice, tips or returns product. Listings containing it are refused before they even reach the owner.
_BANNED = [re.compile(p, re.I) for p in (
    r"\btips?\b", r"\bguarantee\w*", r"\bassured\b", r"sure[\s-]?shot", r"\bjackpot\b", r"\bmultibagger\w*", r"\bpms\b", r"risk[\s-]?free",
    r"portfolio[\s-]+manage\w*", r"\badvisory\b", r"\bresearch analyst\b", r"\b(investment|stock|trading|market)\s+advi[cs]e\w*",
    r"\b(buy|sell|trading|intraday|jackpot|vip|premium)\s+calls?\b", r"\b(paid|vip|premium|buy|sell|intraday)\s+signals?\b",
    r"\b(daily|weekly|monthly|fixed|assured|guaranteed)\s+(returns?|profits?|income)\b", r"\bdouble\s+your\s+money\b", r"\b\d+\s*%\s*(returns?|profits?)\b",
)]
_CONTACT = [re.compile(p, re.I) for p in (
    r"https?://", r"\bwww\.", r"[\w.+-]+@[\w-]+\.\w+", r"(?<!\d)(\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",
    r"\b(whats\s?app|telegram|signal app|t\.me|insta(gram)?|discord)\b",
)]


def _ctl(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", text or "")


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", _ctl(text)).strip()


def body(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _ctl(text).replace("\r", "")).strip()


def _fail(detail: str) -> None:
    raise HTTPException(status_code=422, detail=detail)


def check_wording(*texts: str) -> None:
    joined = " ".join(texts)
    for pattern in _BANNED:
        hit = pattern.search(joined)
        if hit:
            _fail(f"The Exchange doesn't allow tips, calls, signals, advice, portfolio management or promised returns. Please remove “{hit.group(0).strip()}”.")
    for pattern in _CONTACT:
        if pattern.search(joined):
            _fail("Please remove links, emails, phone numbers and chat handles. People will reach you through the Exchange.")


def clean_name(name: str) -> str:
    name = one_line(name)
    if not NAME[0] <= len(name) <= NAME[1] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", name):
        _fail(f"Pick a display name of {NAME[0]}–{NAME[1]} letters or numbers (spaces . _ - allowed). Don't use your email.")
    if re.search(r"admin|owner|edgedesk|official|support|exchange", name, re.I):
        _fail("That name could be mistaken for the site team. Please choose another.")
    return name


def clean_listing(data: dict) -> dict:
    if data.get("accept") is not True:
        _fail("Please tick the box to confirm your listing follows the rules.")
    title, description, price = one_line(str(data.get("title", ""))), body(str(data.get("description", ""))), one_line(str(data.get("price_text", "")))
    category = str(data.get("category", ""))
    if category not in CATEGORIES:
        _fail("Pick a category.")
    if not TITLE[0] <= len(title) <= TITLE[1]:
        _fail(f"The title needs {TITLE[0]}–{TITLE[1]} characters.")
    if not DESC[0] <= len(description) <= DESC[1]:
        _fail(f"Describe the service in {DESC[0]}–{DESC[1]} characters.")
    if len(price) > PRICE:
        _fail(f"Keep the price note under {PRICE} characters (for example “₹999 per month” or “Free”).")
    check_wording(title, description, price)
    return {"title": title, "category": category, "description": description, "price_text": price}


def clean_message(text: str) -> str:
    text = body(text)
    if not 2 <= len(text) <= MSG:
        _fail(f"Messages can be 2–{MSG} characters.")
    return text


def clean_reason(text: str) -> str:
    text = one_line(text)
    if not 5 <= len(text) <= REASON:
        _fail(f"Say what is wrong in 5–{REASON} characters.")
    return text


class Limiter:
    """Sliding-window counter per (person, action). In memory: it only slows abuse, and starting afresh after a restart is harmless."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def hit(self, who: str, action: str, limit: int, window: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        q = self._hits[(who, action)]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status_code=429, detail="You're doing that a lot. Please wait a while and try again.")
        q.append(now)


limiter = Limiter()
