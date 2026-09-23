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

## Auth and roles
Single user, no frontend auth yet. Future Kotak credentials belong only in `backend/.env`; tokens/session material must remain server-side and be encrypted before Mongo persistence.

## Claude AI
- Provider/model: Anthropic `claude-haiku-4-5-20251001` through the server-only `EMERGENT_LLM_KEY`.
- The frontend receives SSE text deltas only and never receives the LLM key.
- Chat messages, summaries, and alerts are persisted independently in `ai_messages`, `ai_summaries`, and `ai_alerts`.
- Outputs are informational, cannot place orders, and are labeled `DEMO ANALYSIS` when the normalized source is simulated.

## Current integration boundary
`backend/lib/settings.py` reads current v2 names: `KOTAK_ACCESS_TOKEN`, `KOTAK_TOTP_SECRET`, `KOTAK_MPIN`, `KOTAK_MOBILE_NUMBER`, `KOTAK_UCC`, `KOTAK_NEO_FIN_KEY`, `KOTAK_VAULT_KEY`, and `KOTAK_MODE`. There is no `KOTAK_CONSUMER_SECRET`. `backend/lib/kotak_client.py` performs server-side TOTP generation, fixed `tradeApiLogin`, MPIN validation, dynamic `baseUrl`/`feedUrl` extraction, and redacted errors. `backend/lib/kotak_feed.py` implements the current JSON-control/native-binary SFeed protocol with dynamic `feedUrl`, 1117/1119 divider handling, 1109 subscriptions, and reconnect backoff. The browser receives only sanitized auth status; live dashboard snapshots remain blocked rather than silently falling back until the feed worker is connected.