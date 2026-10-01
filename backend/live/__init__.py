"""LIVE SIGNAL ENGINE: current market data + config.json -> a signal. Never imports `research`.

LIVE DATA -> validation -> indicators -> option-chain analysis -> strike scoring -> confidence -> risk -> signal.
It reads parameters only through `shared.config.load_config`; it has no access to research_db, historical
labels, backtest results or training data. Storage is `live_db`.
"""
