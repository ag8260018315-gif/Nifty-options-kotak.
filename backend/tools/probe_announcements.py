"""Shows what NSE's announcements site returns to THIS machine (run it on your PC, and ask Claude to read the output):

    python tools/probe_announcements.py TCS
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main(symbol: str) -> int:
    import httpx

    from premium import announcements as a

    async with httpx.AsyncClient(timeout=10, headers=a.HEADERS, follow_redirects=True) as c:
        try:
            home = await c.get(a.HOME)
            print("home:", home.status_code, "cookies:", len(c.cookies))
            r = await c.get(a.URL, params={"index": "equities", "symbol": symbol})
            print("api:", r.status_code, r.headers.get("content-type"))
            body = r.json()
        except Exception as exc:  # noqa: BLE001
            print("FAILED:", type(exc).__name__, exc)
            return 1
    rows = body.get("data") if isinstance(body, dict) else body
    print("rows:", len(rows) if isinstance(rows, list) else type(rows).__name__)
    if isinstance(rows, list) and rows:
        print("fields:", sorted(rows[0]))
        print("first row:", rows[0])
    items = a.parse(body)
    print("parsed items:", len(items))
    for item in items[:5]:
        print(" -", item["published_at"], item["title"][:90], item["sentiment"]["tone"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "TCS")))
