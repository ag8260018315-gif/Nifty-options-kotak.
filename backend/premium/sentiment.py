"""Plain keyword reading of a headline or exchange announcement: a topic and a tone, with the words that decided it. Pure.

This is NOT understanding: it counts words from two short lists and says which words it saw, so a reader can overrule it.
"Mixed" means both kinds of words appeared; "Neutral" means neither did. It never says a story is true, and it is not a
prediction of what the price will do."""
import re
from typing import Any

POSITIVE = ("profit rises", "profit jumps", "profit up", "net profit up", "record profit", "beats estimates", "beat estimates", "strong results", "upgrade", "upgraded",
            "raises target", "buy rating", "outperform", "order win", "bags order", "wins order", "secures order", "new order", "contract win", "dividend", "bonus",
            "buyback", "acquires", "acquisition", "expansion", "approval", "approved", "all-time high", "record high", "surge", "rally", "gains", "growth", "wins")
NEGATIVE = ("profit falls", "profit drops", "profit down", "net loss", "loss widens", "misses estimates", "miss estimates", "weak results", "downgrade", "downgraded",
            "cuts target", "sell rating", "underperform", "penalty", "fine", "probe", "investigation", "raid", "fraud", "default", "resigns", "resignation", "lawsuit",
            "ban", "recall", "shutdown", "plunge", "slump", "falls", "declines", "tumbles", "slashes", "warning", "insolvency", "delisting")
TOPICS = (
    ("Results", ("result", "quarterly", "q1", "q2", "q3", "q4", "earnings", "financial results", "profit", "revenue")),
    ("Dividend / buyback", ("dividend", "buyback", "bonus", "split", "record date")),
    ("Board / management", ("board meeting", "appoint", "resign", "ceo", "cfo", "director", "management")),
    ("Deal / order", ("order", "contract", "acqui", "merger", "stake", "agreement", "tie-up", "partnership")),
    ("Rating / analyst", ("rating", "target price", "upgrade", "downgrade", "brokerage")),
    ("Legal / regulatory", ("sebi", "penalty", "fine", "court", "lawsuit", "probe", "investigation", "notice", "tax")),
)
NOTE = "Keyword reading only: it counts words from short lists and shows which ones. It can be wrong, ignores context and is not a forecast."


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if re.search(r"(?<![a-z])" + re.escape(w), text)]


def read(text: str) -> dict[str, Any]:
    low = (text or "").lower()
    pos, neg = _hits(low, POSITIVE), _hits(low, NEGATIVE)
    tone = "Mixed" if pos and neg else "Positive" if pos else "Negative" if neg else "Neutral"
    topic = next((name for name, words in TOPICS if _hits(low, words)), "General")
    return {"tone": tone, "topic": topic, "positive_words": pos[:4], "negative_words": neg[:4]}


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"Positive": 0, "Negative": 0, "Mixed": 0, "Neutral": 0}
    for item in items:
        counts[item["sentiment"]["tone"]] += 1
    lead = "Mixed" if counts["Positive"] and counts["Negative"] else "Positive" if counts["Positive"] > counts["Negative"] else "Negative" if counts["Negative"] > counts["Positive"] else "Neutral"
    return {"counts": counts, "overall": lead if items else "None", "items": len(items), "note": NOTE}
