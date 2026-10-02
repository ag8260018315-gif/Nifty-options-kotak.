"""AUTO-TRADER (paper by default). Consumes finished LIVE signals; never imports `research`.

  signal -> guardrails -> broker.fill -> position -> exit rules (stop / target / square-off / kill switch) -> P&L

Modes (env TRADING_MODE): OFF = does nothing; PAPER = pretend fills, no orders ever leave this server (default);
LIVE = real orders. LIVE is refused until a verified Kotak order adapter exists (see brokers.KotakBroker).
"""
