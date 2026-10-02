import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiGet, apiPost } from "@/lib/api";

// AUTO-TRADER. Paper mode by default: pretend fills against live prices, no order ever reaches the broker.

interface Trade {
  trade_id: string;
  symbol: string;
  mode: string;
  direction: "CE" | "PE";
  strike: number;
  quantity: number;
  entry_premium: number;
  stop: number;
  target: number;
  status: "OPEN" | "CLOSED";
  exit_premium: number | null;
  exit_reason: string | null;
  pnl: number | null;
  opened_at: string;
}

interface TraderStatus {
  mode: "OFF" | "PAPER" | "LIVE";
  real_orders: boolean;
  broker_error: string | null;
  killed: boolean;
  kill_reason: string | null;
  settings: { lots: number; max_open_positions: number; max_trades_per_day: number; max_daily_loss: number; squareoff_time: string };
  account: { start_capital: number; realised_pnl: number; equity: number; available: number; return_pct: number | null };
  today: { trades: number; open_positions: number; pnl: number; wins: number; losses: number };
  open_positions: Trade[];
}

const rupees = (v: number) => `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default function TradingPanel({ isOwner }: { isOwner: boolean }) {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["trading-status"], queryFn: () => apiGet<TraderStatus>("/trading/status"), refetchInterval: 4000, retry: false });
  const trades = useQuery({ queryKey: ["trading-trades"], queryFn: () => apiGet<{ trades: Trade[] }>("/trading/trades?limit=15"), refetchInterval: 8000, retry: false });
  const toggle = useMutation({
    mutationFn: (kill: boolean) => apiPost(kill ? "/trading/kill" : "/trading/resume"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["trading-status"] }),
  });
  const s = status.data;
  const box = "rounded-md border border-[#202b42] bg-[#090d15] px-3 py-2";
  const paper = s?.mode !== "LIVE";
  return (
    <section id="trader" aria-label="Auto-trader" className="scroll-mt-4 space-y-3">
      <div data-testid="trader-banner" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-amber-300">
        <span className="text-xs font-bold uppercase tracking-[0.2em]">Auto-trader · {s?.mode ?? "…"}</span>
        <span className="text-[11px] opacity-80">{paper ? "Practice trades with pretend money. No orders are sent to Kotak." : "Real orders enabled."}</span>
      </div>
      <Card data-testid="trader-card" className="border-[#202b42] bg-[#0c0f17]/95">
        <CardHeader className="flex-row items-center justify-between border-b border-[#202b42] px-4 py-3">
          <CardTitle className="font-heading text-base text-slate-100">Trades from live signals</CardTitle>
          <div className="flex items-center gap-2">
            {s?.killed && <Badge data-testid="trader-killed" className="border-rose-500/30 bg-rose-500/10 text-[10px] text-rose-300">STOPPED</Badge>}
            {isOwner && s && (
              <Button data-testid="trader-kill-toggle" size="sm" variant="outline" className="border-[#2a364f] bg-transparent text-xs text-slate-300" disabled={toggle.isPending} onClick={() => toggle.mutate(!s.killed)}>
                {s.killed ? "Resume trading" : "Stop trading now"}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4 p-4">
          {status.isError && <p className="text-xs text-slate-500">The auto-trader is unavailable right now.</p>}
          {s?.broker_error && <p data-testid="trader-broker-error" className="rounded border border-rose-500/25 bg-rose-500/5 px-3 py-2 text-xs text-rose-300">Real orders are disabled: {s.broker_error}</p>}
          {s && (
            <>
              {s.account.start_capital > 0 && (
                <div data-testid="trader-account" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div className={box}><p className="text-[10px] text-slate-500">Practice starting money</p><p className="mt-1 font-mono text-lg font-bold text-slate-100">{rupees(s.account.start_capital)}</p></div>
                  <div className={box}><p className="text-[10px] text-slate-500">Practice balance now</p><p data-testid="trader-equity" className={`mt-1 font-mono text-lg font-bold ${s.account.equity < s.account.start_capital ? "text-rose-300" : "text-emerald-300"}`}>{rupees(s.account.equity)}</p></div>
                  <div className={box}><p className="text-[10px] text-slate-500">Total return</p><p className={`mt-1 font-mono text-lg font-bold ${(s.account.return_pct ?? 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>{s.account.return_pct === null ? "—" : `${s.account.return_pct.toFixed(2)}%`}</p></div>
                  <div className={box}><p className="text-[10px] text-slate-500">Free cash for new trades</p><p className="mt-1 font-mono text-lg font-bold text-slate-100">{rupees(s.account.available)}</p></div>
                </div>
              )}
              {s.account.start_capital <= 0 && <p className="text-[10px] text-slate-500">Tip: set TRADING_START_CAPITAL (for example 20000) on the server to track a practice balance and return.</p>}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className={box}><p className="text-[10px] text-slate-500">Today's practice P&L</p><p data-testid="trader-pnl" className={`mt-1 font-mono text-lg font-bold ${s.today.pnl < 0 ? "text-rose-300" : "text-emerald-300"}`}>{rupees(s.today.pnl)}</p></div>
                <div className={box}><p className="text-[10px] text-slate-500">Trades today</p><p className="mt-1 font-mono text-lg font-bold text-slate-100">{s.today.trades} <span className="text-[10px] font-normal text-slate-500">of {s.settings.max_trades_per_day}</span></p></div>
                <div className={box}><p className="text-[10px] text-slate-500">Wins / losses</p><p className="mt-1 font-mono text-lg font-bold text-slate-100">{s.today.wins} / {s.today.losses}</p></div>
                <div className={box}><p className="text-[10px] text-slate-500">Open now</p><p data-testid="trader-open" className="mt-1 font-mono text-lg font-bold text-slate-100">{s.open_positions.length}</p></div>
              </div>
              <p className="text-[10px] text-slate-500">Safety limits: {s.settings.lots} lot, max {s.settings.max_open_positions} open, stop for the day at {rupees(-s.settings.max_daily_loss)}, close everything at {s.settings.squareoff_time} IST.</p>
            </>
          )}
          {trades.data && trades.data.trades.length > 0 && (
            <div className="overflow-x-auto" data-testid="trader-trades">
              <table className="w-full text-left text-xs text-slate-400">
                <thead><tr className="text-[10px] text-slate-500"><th className="py-1">Time</th><th>Trade</th><th>Entry</th><th>Exit</th><th>Why</th><th className="text-right">P&L</th></tr></thead>
                <tbody>
                  {trades.data.trades.map((t) => (
                    <tr key={t.trade_id} className="border-t border-[#202b42]">
                      <td className="py-1">{new Date(t.opened_at).toLocaleTimeString("en-IN")}</td>
                      <td>{t.symbol} {t.strike} {t.direction}</td>
                      <td>{t.entry_premium}</td>
                      <td>{t.exit_premium ?? "open"}</td>
                      <td>{t.exit_reason ?? "—"}</td>
                      <td className={`text-right ${t.pnl !== null && t.pnl < 0 ? "text-rose-300" : "text-emerald-300"}`}>{t.pnl === null ? "—" : rupees(t.pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {trades.data && trades.data.trades.length === 0 && <p className="text-xs text-slate-500">No practice trades yet. A trade opens only when a live signal passes every safety check.</p>}
          <p className="text-[10px] text-slate-600">Practice fills include a small price slippage. Results are not a prediction of real trading. Practice for 1-2 weeks before ever considering real money.</p>
        </CardContent>
      </Card>
    </section>
  );
}
