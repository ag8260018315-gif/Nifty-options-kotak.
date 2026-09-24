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

## Auth and roles
Single user, no frontend auth yet. Future Kotak credentials belong only in `backend/.env`; tokens/session material must remain server-side and be encrypted before Mongo persistence.

## Claude AI
- Provider/model: Anthropic `claude-haiku-4-5-20251001` through the server-only `EMERGENT_LLM_KEY`.
- The frontend receives SSE text deltas only and never receives the LLM key.
- Chat messages, summaries, and alerts are persisted independently in `ai_messages`, `ai_summaries`, and `ai_alerts`.
- Outputs are informational, cannot place orders, and are labeled `DEMO ANALYSIS` when the normalized source is simulated.

## Current integration boundary
`backend/lib/settings.py` reads current v2 names: `KOTAK_ACCESS_TOKEN`, `KOTAK_TOTP_SECRET`, `KOTAK_MPIN`, `KOTAK_MOBILE_NUMBER`, `KOTAK_UCC`, `KOTAK_NEO_FIN_KEY`, `KOTAK_VAULT_KEY`, and `KOTAK_MODE`. There is no `KOTAK_CONSUMER_SECRET`. `backend/lib/kotak_client.py` performs server-side TOTP generation, fixed `tradeApiLogin`, MPIN validation, encrypted session restoration, dynamic `baseUrl`/`feedUrl` extraction, and consumer-key REST calls. `backend/lib/kotak_feed.py` decodes current 7207/7208 native-batch packets with 1117 exchange dividers. `backend/lib/instruments.py` parses live NIFTY, BANKNIFTY, and FINNIFTY contracts instead of guessing option tokens or strike steps. `backend/lib/multi_feed_worker.py` owns the single resilient socket, three named index subscriptions, per-index ATM resubscriptions, Black-Scholes IV/Delta normalization, five-second history snapshots, opening reports, freshness states, and throttled ATM/expiry alerts.