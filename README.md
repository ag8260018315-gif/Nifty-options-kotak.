# Nifty Options Desk (Kotak Neo)

A read-only options terminal for **NIFTY, BANKNIFTY and FINNIFTY**. It streams live index and option-chain data from the Kotak Neo Trade API, shows PCR / OI / Greeks, and produces CE/PE trade signals from a strategy whose parameters are tuned offline by a walk-forward research engine. It never places orders.

- Frontend: Vite + React 19 + TypeScript + Tailwind v4 + shadcn/ui, deployed on **Vercel**
- Backend: FastAPI + MongoDB (motor), deployed on **Render**
- Live site: https://nifty-options-kotak.vercel.app

## How it fits together

```
RESEARCH (backend/research)  ->  config.json  ->  LIVE (backend/live)  ->  dashboard
   historical bars only          parameters        live ticks only
```

The two engines are deliberately separate. Research never produces a live trade; live never reads history, backtests or training data. The only thing that travels between them is a validated `config.json`.

## Repository layout

```
backend/
  server.py        FastAPI app; every route lives under /api
  routers/         dashboard, auth, access, ai, live_signals, research_api, public
  lib/             Kotak client + feed worker, instruments, DB, AI service, access control
  research/        walk-forward research engine (writes config.json)
  live/            live signal engine (reads config.json)
  shared/          code both engines use: indicators, strategy, config contract
  tools/           ingest_research_data.py (one-way bridge into research data)
  tests/           pytest suite
frontend/          React app (src/pages, src/components, src/lib)
memory/SPEC.md     living spec with the detailed design notes
```

### `backend/research/` - walk-forward research
- `optimize.py` searches parameters on rolling train/test windows and reports **out-of-sample** results.
- `backtest.py` scores signals at a fixed horizon (index direction, not option P&L, since historical premiums are not stored).
- `data.py` loads bars from CSV or `research_db`; `store.py` saves runs.
- Its only output toward trading is `config.json`, written with `--apply`, and only when the run status is OK and the lookahead check passed.

```bash
cd backend
python -m research.cli --csv bars.csv --symbol NIFTY            # run + store the report
python -m research.cli --csv bars.csv --symbol NIFTY --apply    # also write config.json
```
Options: `--horizon` (bars, default 15), `--train-days` (10), `--test-days` (3), `--before YYYY-MM-DD`.

### `backend/live/` - live signal engine
A pure function of `(LiveInputs, EngineConfig)`. Every 5 seconds, per index, the runner (`runner.py`) does:
guard validation (`guard.py`) -> indicators -> option-chain PCR -> strike scoring (`strikes.py`) -> confidence -> risk gate and levels (`risk.py`) -> signal. Signals and their outcomes (`outcomes.py`) are stored in `live_db`.

- `config.json` is re-read every cycle, so a new config applies without a restart.
- The guard blocks stale data (older than 5 s), forming or future candles, expired contracts, and non-LIVE or non-Kotak sources. DEMO data is never persisted.
- Each signal stores the exact inputs and config that produced it; `GET /api/live/signals/{id}/replay` recomputes it.
- **Confidence** is a signal-strength score, not a win probability. Out-of-sample accuracy from research is shown separately as `historical_validation` ("Not validated" when absent).

### `backend/shared/` - the common ground
- `indicators.py`: EMA and RSI.
- `strategy.py`: `decide()`, the signal model (weighted EMA + RSI + OI/PCR). Research and live call the same function, so research measures exactly what runs live.
- `config.py`: the `EngineConfig` contract for `config.json` (`extra="forbid"`, so nothing but parameters and aggregate stats can pass through). See `backend/config.example.json`.

## Frontend panels

| Panel | What it shows |
|---|---|
| Market ticker and index cards | Spot, change and feed state (LIVE / STALE / EXPIRED / MARKET CLOSED) for the three indices |
| Index chart | Candles with selectable intervals |
| Option chain, PCR / OI, Greeks ladder | ATM-centred chain, OI structure, IV/Delta |
| Order blocks | Order-block markers on the chart |
| Live signal | Current CE/PE/WAIT signal, confidence, validation, signal history and replay |
| Research / historical analysis | Walk-forward results and runs, visually separate from live |
| Engine overview and feature guide | Animated explanations of how the engines and features work |
| Pre-trade checks | Position-size and risk calculator |
| AI analyst | Claude-streamed explanations, chat and summaries (informational only) |
| Access admin / Upgrade / Landing | Sign-in, trials and plans |

## Running locally

Prerequisites: Python 3.11+, Node 20+, a MongoDB instance.

```bash
# backend  -> http://localhost:8001
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# frontend -> http://localhost:3000
cd frontend
yarn install && yarn dev
```

The Vite dev server proxies `/api/*` to `localhost:8001`, so frontend code always calls relative `/api/...` paths.

Tests: `cd backend && pytest -n 0`.

## Configuration (backend environment variables)

| Variable | Purpose |
|---|---|
| `MONGO_URL`, `DB_NAME` | MongoDB connection and app database (required) |
| `LIVE_DB_NAME` | Live signals database (defaults to `DB_NAME`) |
| `RESEARCH_DB_NAME` | Research database (defaults to `<DB_NAME>_research`) |
| `ENGINE_CONFIG_PATH` | Where `config.json` lives (defaults to `backend/config.json`) |
| `KOTAK_MODE` | `DEMO` (default) or `LIVE` |
| `KOTAK_ACCESS_TOKEN`, `KOTAK_MOBILE_NUMBER`, `KOTAK_UCC`, `KOTAK_MPIN`, `KOTAK_TOTP_SECRET`, `KOTAK_VAULT_KEY` | Kotak Neo credentials; the session is stored encrypted, secrets never reach the frontend |
| `EMERGENT_LLM_KEY` | Key for the AI analyst (server-side only) |
| `CORS_ORIGINS` | Comma-separated allowed origins (default `*`) |

Without Kotak credentials the app stays explicitly in DEMO mode and never claims LIVE.

## Deployment

- **Backend on Render**: run `uvicorn server:app --host 0.0.0.0 --port $PORT` from `backend/`, with the environment variables above. Public URL: `https://nifty-options-kotak.onrender.com`.
- **Frontend on Vercel**: project root `frontend/`, build `yarn build`. `frontend/vercel.json` rewrites `/api/*` to the Render backend, so the browser sees a single origin.
- **Updating strategy parameters**: run the research CLI with `--apply`, then commit/deploy the new `backend/config.json`, or point `ENGINE_CONFIG_PATH` at a persistent disk. The live engine picks it up on its next cycle.

## Further reading

`memory/SPEC.md` has the full design notes: data model, feed handling, anti-lookahead rules and API routes.
