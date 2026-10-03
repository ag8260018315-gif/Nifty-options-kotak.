# NIFTY Options Desk — living spec

## Purpose
Single-user read-only NIFTY options terminal using the current Kotak Neo Trade API flow. DEMO remains explicit and is the default until live server configuration is complete.

## Data model
- `DashboardSnapshot`: server-normalized spot, option chain, market structure, signal, feed health, expiry, and server timestamp.
- `AuthStatus`: DEMO/LIVE configuration and connection state without returning secrets.
- Supported symbols: NIFTY, BANKNIFTY, FINNIFTY.

## Key flows
1. Dashboard loads a server-generated normalized snapshot through `/api/market-data/dashboard`.
2. Symbol selector swaps the snapshot without changing the UI contract.
3. Connect Kotak Neo opens the secure setup panel; without server-side credentials the UI stays explicitly DEMO and does not silently claim LIVE.
4. Demo mode requires explicit confirmation through `/api/auth/demo`.
5. Claude Haiku 4.5 streams signal explanations, dashboard chat answers, end-of-day summaries, and CE/PE/WAIT alerts through `/api/ai/stream`; DEMO-derived responses are explicitly labeled.
6. In LIVE mode, one backend SFeed worker restores or refreshes the encrypted Kotak session, loads current NIFTY/BANKNIFTY/FINNIFTY contracts, subscribes to all three indices plus ATM ±10 CE/PE windows, and publishes separate normalized snapshots.
7. `/api/market-data/feed-status` drives LIVE only for ticks newer than five seconds; it otherwise reports STALE, EXPIRED, or MARKET CLOSED without falling back to DEMO.
8. At the first tick after 09:16 IST, the worker persists a three-index opening report covering fresh spot, divider verification, ±10 option windows, paired CE/PE ticks, and socket health.
9. Alert controls persist an ATM threshold (default one full strike), 60-second cooldown, and quiet hours from 15:30 to 09:15 IST through `/api/market-data/alert-settings`.
10. `/api/market-data/export.csv?symbol=...` downloads only allow-listed, verified `KOTAK_NEO` normalized option snapshots from the current IST trading day. It returns 404 for DEMO, waiting, zero, or unavailable data and remains available after close for the last verified current-day snapshots.
11. `/api/market-data/export-archive` lists per-index availability, snapshot/row counts, capture times, and a 15:31 IST auto-prepared manifest. FINNIFTY emits an `EXPORT_READY` alert when its first complete verified chain unlocks.

## Auth and roles
Single user, no frontend auth yet. Future Kotak credentials belong only in `backend/.env`; tokens/session material must remain server-side and be encrypted before Mongo persistence.

## Claude AI
- Provider/model: Anthropic `claude-haiku-4-5-20251001` through the server-only `EMERGENT_LLM_KEY`.
- The frontend receives SSE text deltas only and never receives the LLM key.
- Chat messages, summaries, and alerts are persisted independently in `ai_messages`, `ai_summaries`, and `ai_alerts`.
- Outputs are informational, cannot place orders, and are labeled `DEMO ANALYSIS` when the normalized source is simulated.

## Current integration boundary
`backend/lib/settings.py` reads current v2 names: `KOTAK_ACCESS_TOKEN`, `KOTAK_TOTP_SECRET`, `KOTAK_MPIN`, `KOTAK_MOBILE_NUMBER`, `KOTAK_UCC`, `KOTAK_NEO_FIN_KEY`, `KOTAK_VAULT_KEY`, and `KOTAK_MODE`. There is no `KOTAK_CONSUMER_SECRET`. `backend/lib/kotak_client.py` performs server-side TOTP generation, fixed `tradeApiLogin`, MPIN validation, encrypted session restoration, dynamic `baseUrl`/`feedUrl` extraction, and consumer-key REST calls. `backend/lib/kotak_feed.py` decodes current 7207/7208 native-batch packets with 1117 exchange dividers. `backend/lib/instruments.py` parses live NIFTY, BANKNIFTY, and FINNIFTY contracts instead of guessing option tokens or strike steps. `backend/lib/multi_feed_worker.py` owns the single resilient socket, three named index subscriptions, per-index ATM resubscriptions, Black-Scholes IV/Delta normalization, five-second history snapshots, opening reports, freshness states, and throttled ATM/expiry alerts.

## Research engine vs live signal engine (strictly separated)
```
RESEARCH (research/, research_db)  ->  parameters  ->  config.json  ->  LIVE (live/, live_db)  ->  dashboard
```
- **Research engine** (`backend/research/`): historical bars only (`research_db.candles`, filled from CSV or by the explicit one-way bridge `backend/tools/ingest_research_data.py`, completed days only). Walk-forward parameter search (`optimize.py`), backtests (`backtest.py`), confidence-band calibration. Stores `backtests`, `experiments`, `optimization_results` in **research_db**. Its only output toward trading is `shared.config.save_config` -> `config.json`. It never produces a live trade and never imports `live`.
- **Live signal engine** (`backend/live/`): a pure function of (`LiveInputs`, `EngineConfig`). Pipeline: guard validation -> indicators -> option-chain analysis (PCR) -> strike scoring -> confidence -> risk gate/levels -> signal. Reads parameters only via `shared.config.load_config` (re-read every cycle). Never imports `research`, never touches `research_db`, historical labels, backtests or training data. Stores `live_signals` and `signal_outcomes` in **live_db** (default: the application database that already holds live ticks, chains and candles; `LIVE_DB_NAME` overrides). `research_db` defaults to `<DB_NAME>_research` (`RESEARCH_DB_NAME` overrides).
- **Shared** (`backend/shared/`): pure indicator math, the signal-scoring function (`strategy.py`, so research measures exactly what live runs), and the config contract. `EngineConfig` is `extra="forbid"`: nothing but parameters and aggregate validation stats can travel in config.json.
- **Anti-lookahead** (`live/guard.py`): blocks on data stamped after `as_of`, forming/future candles, stale spot/chain (default 5 s), unordered candles, expired contract, non-LIVE feed or non-Kotak source. Each signal stores the exact inputs + config that produced it and a fingerprint; `GET /api/live/signals/{id}/replay` recomputes it from those alone. Research proves its own causality per run (`check_no_lookahead`), and a run with a failed check writes no config.
- **Accuracy rule**: every live signal carries `confidence` ("Current signal confidence", a strength score) and, separately, `historical_validation` (out-of-sample accuracy from research, or "Not validated"). The UI shows them in separate labelled tiles; confidence is never called accuracy.
- **Research scope limit**: outcomes are index-direction at a fixed horizon, not option P&L (historical option premiums are not stored). OI weighting is only tuned on bars that carry a recorded PCR.
- **Routes**: `/api/live/{signal,signals,signals/{id}/replay,config}`; `/api/research/{summary,runs}` and admin-only `POST /api/research/run` (`apply: true` writes config.json). CLI: `python -m research.cli --csv bars.csv [--apply]`.
- **UI**: `EnginePanels.tsx` - "LIVE SIGNAL" section and a separate "RESEARCH / HISTORICAL ANALYSIS" section, each with its own banner.
- **Tests**: `backend/tests/test_engines_core.py`, `test_live_runner.py` (run `pytest -n 0`): import-boundary AST checks, config smuggling, guard cases, future-candle invariance, replay, walk-forward, leakage detector, DEMO never persisted.

## Auto-trader (`backend/trading/`, PAPER by default)
Consumes finished live signals (never `research`). Pure rules in `engine.py` (entry guardrails, stop/target/square-off/kill-switch exits, P&L); `brokers.py`: `PaperBroker` (pretend fills with slippage) and `KotakBroker`, which deliberately refuses because the Kotak order endpoint is unverified. `TRADING_MODE` = OFF | PAPER (default) | LIVE; LIVE also needs `TRADING_LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK` and currently falls back to OFF with a visible error. Limits via env: `TRADING_LOTS`, `TRADING_LOT_SIZE_<INDEX>` (defaults must be verified), `TRADING_MAX_OPEN`, `TRADING_MAX_TRADES_PER_DAY`, `TRADING_MAX_DAILY_LOSS`, `TRADING_SLIPPAGE_PCT`, `TRADING_SQUAREOFF`. Trades live in `live_db.auto_trades`; the kill switch in `live_db.trading_state`. Routes: `/api/trading/{status,trades}`, admin `POST /kill|/resume`. Demo data never trades. Tests: `tests/test_trading.py`.

## Automatic daily research (`backend/jobs/`)
`jobs/research_scheduler.py` runs inside the backend every weekday after 15:45 IST (once per day, tracked in `research_db.job_state`): `jobs/bridge.py` copies the finished sessions' index candles (and per-minute PCR) from live storage into `research_db.candles` (never today), then once `RESEARCH_TRAIN_DAYS + RESEARCH_TEST_DAYS` (default 10 + 3) sessions exist it runs the walk-forward research per index and stores the report in `research_db.optimization_results`. `config.json` is written only if `RESEARCH_AUTO_APPLY=true`; otherwise the owner applies the latest successful result with `POST /api/research/apply`. `jobs` is the only place that touches both stores; neither engine imports it. Note: the config file lives on the server disk, which is wiped on a redeploy on hosts with ephemeral disks (point `ENGINE_CONFIG_PATH` at a persistent disk or re-apply after a deploy).

Auto-trader practice account: `TRADING_START_CAPITAL` (rupees, default 0 = off) tracks equity = start + realised P&L, free cash = equity - cost of open trades, and total return %. A paper entry is skipped if one lot would not fit in the free cash. Shown in the Auto-trader panel (`status.account`).

## Premium: SENSEX, index charts and stock analysis (`backend/premium/`, `lib/premium.py`, `frontend/src/pages/Premium.tsx`)
- **Access**: premium is a separate paid entitlement, not the free trial or an ordinary approved viewer. Holders are the owner(s) plus emails granted `premium_access` until a date (owner only: `POST /api/access/admin/premium`, `.../premium/revoke`, list `GET`; the Access panel has a Premium section). Payment is manual until a gateway exists. `lib.premium.require_premium` is a FastAPI dependency on the WHOLE `/api/premium/*` router (server.py), so free users get 403 `premium_required` and 401/402 as usual; the UI lock is only presentation. `/api/access/me` returns `premium` and `premium_until`; `POST /api/access/premium-request` emails the owner (max one per 6 h).
- **Data**: genuine Kotak Neo SFeed ticks only. NIFTY/BANKNIFTY/FINNIFTY come from the existing worker and `candle_store`; SENSEX (default feed name `bse_cm|SENSEX`, override `PREMIUM_SENSEX_SUBSCRIPTION`) and a large-cap NSE stock list (default ~49 symbols, override `PREMIUM_STOCKS`) are subscribed by `KotakSFeed._subscribe_premium`, with stock tokens resolved from Kotak's own nse_cm scrip master. Ticks are routed by `kind="premium"` straight to `premium.market.premium_market` (quotes, 1-minute candles with volume deltas, persisted to `premium_candles`) and never touch NIFTY state. No demo or simulated values: with no live feed the routes report `NO_FEED`. Market state is OPEN / DELAYED (hours open but ticks older than 15 s) / CLOSED.
- **Safety for the existing feed**: the premium subscription is isolated in its own try/except; a circuit breaker switches it off after two socket drops within 45 s of subscribing; `PREMIUM_FEED=off` disables it entirely.
- **Analysis** (`premium/analysis.py`, pure): EMA 9/21, RSI 14, MACD, Bollinger, ATR, VWAP (stocks), pivots from the previous recorded session, swing support/resistance, volume analysis (relative volume, spike, buying pressure), trend label, and a transparent additive BUY/SELL/NEUTRAL score from closed candles only (needs 35 closed candles; otherwise BUILDING). The stock list ranks "potential buying setups". Informational, not advice.
- **Known limits**: no historical backfill (charts start when ticks start arriving), indices publish no volume, pivots need one earlier recorded session, and SENSEX and stock subscriptions must be confirmed on a live account with `python tools/probe_premium_symbols.py` during market hours. Exchange data redistribution terms apply before selling live prices.
- **UI**: `/premium` route (`pages/Premium.tsx`), a "Premium" link in the main header, `components/premium/*` (interactive SVG chart with pan/zoom/crosshair, panels, indices, stocks). `vercel.json` has an SPA fallback so `/premium` survives a refresh.
- **Tests**: `tests/test_premium.py` (403 for trial/viewer/lapsed/expired, 401 signed out, forged cookie, grant/revoke, free users still reach the old dashboard, candles/volume/persistence, feed classification, circuit breaker) and `tests/test_premium_analysis.py`.

### Premium update: stock list, breakout watchlist and news
- The stock universe is static (`premium.universe.static_universe`, ~125 large caps, override `PREMIUM_STOCKS`) and configured when the router loads, so `/api/premium/stocks` lists every stock even when the market is closed or no feed is connected (rows have `quote: null` until a real price exists). Last received quotes are saved to `premium_quotes` and restored (`ensure_quotes`) so prices show after hours and after a restart; a live tick always replaces a stored one.
- `GET /api/premium/stocks/breakouts` (`premium/breakout.py`): stocks 0-2% below their nearest resistance with enough candles, ranked by a 0-100 SCORE (proximity, volume, trend, momentum, VWAP). It is explicitly NOT a probability and the response carries `accuracy.validated=false`; no success rate (e.g. "90%") is claimed because no historical test of the rule exists. Each of the top 10 carries recent headlines from Google News RSS (`premium/news.py`: title/source/time/link only, http(s) links only, cached 10 min, `unavailable` instead of invented items on failure).
- UI: "Top 10 breakout watchlist" at the top of the Stocks tab; each row expands to reasons, news and the full chart/analysis.
