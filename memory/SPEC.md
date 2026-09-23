# NIFTY Options Desk — living spec

## Purpose
Single-user read-only NIFTY options terminal migrating the future live data boundary to Kotak Neo v6. The current build is intentionally DEMO-first because no live credentials are configured.

## Data model
- `DashboardSnapshot`: server-normalized spot, option chain, market structure, signal, feed health, expiry, and server timestamp.
- `AuthStatus`: DEMO/LIVE configuration and connection state without returning secrets.
- Supported symbols: NIFTY, BANKNIFTY, FINNIFTY.

## Key flows
1. Dashboard loads a server-generated normalized snapshot through `/api/market-data/dashboard`.
2. Symbol selector swaps the snapshot without changing the UI contract.
3. Connect Kotak Neo opens the secure setup panel; without server-side credentials the UI stays explicitly DEMO and does not silently claim LIVE.
4. Demo mode requires explicit confirmation through `/api/auth/demo`.

## Auth and roles
Single user, no frontend auth yet. Future Kotak credentials belong only in `backend/.env`; tokens/session material must remain server-side and be encrypted before Mongo persistence.

## Current integration boundary
`backend/lib/settings.py` reads `KOTAK_MODE` and the five Kotak credential fields from environment variables. `backend/lib/token_vault.py` is the server-only Fernet primitive for encrypting future session material with `KOTAK_VAULT_KEY`; the current DEMO flow never creates or persists a live token. `backend/routers/auth.py` exposes safe status/connect contracts. Actual v6 TOTP and SFeed websocket work is intentionally the next credentialed integration step.