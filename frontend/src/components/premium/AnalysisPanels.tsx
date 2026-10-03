import { price, signed, tone, whole, type Action, type Analysis, type MarketInfo, type Quote } from "@/lib/premium";

const box = "rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3";

export function MarketBadge({ market }: { market: MarketInfo }) {
  const styles: Record<MarketInfo["state"], string> = {
    OPEN: "border-emerald-500/35 bg-emerald-950/70 text-emerald-300",
    DELAYED: "border-amber-500/35 bg-amber-950/70 text-amber-300",
    CLOSED: "border-zinc-700/60 bg-zinc-900/90 text-zinc-300",
    NO_FEED: "border-rose-500/35 bg-rose-950/70 text-rose-300",
  };
  const label = market.state === "OPEN" ? "LIVE" : market.state === "NO_FEED" ? "NO LIVE FEED" : market.state === "CLOSED" ? "MARKET CLOSED" : "DELAYED";
  return (
    <span data-testid="market-badge" title={market.message} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold tracking-[0.12em] ${styles[market.state]}`}>
      <span className={`size-1.5 rounded-full ${market.state === "OPEN" ? "animate-pulse bg-emerald-400" : market.state === "DELAYED" ? "bg-amber-400" : market.state === "NO_FEED" ? "bg-rose-400" : "bg-zinc-500"}`} />
      {label}
    </span>
  );
}

export function QuoteHeader({ name, quote, market }: { name: string; quote: Quote | null; market: MarketInfo }) {
  return (
    <div data-testid="quote-header" className={`${box} flex flex-wrap items-end justify-between gap-3`}>
      <div>
        <div className="flex items-center gap-2">
          <h2 className="font-heading text-lg font-semibold text-white">{name}</h2>
          <MarketBadge market={market} />
        </div>
        <p data-testid="quote-ltp" className="mt-1 font-mono text-3xl font-bold tabular-nums text-white">{quote ? price(quote.ltp) : "—"}</p>
        <p className={`font-mono text-sm tabular-nums ${tone(quote?.change)}`}>{quote ? `${signed(quote.change)} (${signed(quote.change_pct, "%")})` : market.message}</p>
      </div>
      {quote && (
        <dl className="grid grid-cols-4 gap-x-5 gap-y-1 text-[11px]">
          {[["Open", quote.open], ["High", quote.high], ["Low", quote.low], ["Prev close", quote.prev_close]].map(([label, value]) => (
            <div key={String(label)}>
              <dt className="text-slate-500">{String(label)}</dt>
              <dd className="font-mono tabular-nums text-slate-200">{price(value as number | null)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

const ACTION_STYLE: Record<Action, string> = {
  BUY: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  SELL: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  NEUTRAL: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  BUILDING: "border-sky-500/30 bg-sky-500/10 text-sky-300",
};

export function ActionPill({ action, strength }: { action: Action; strength?: string | null }) {
  return <span data-testid="signal-action" className={`inline-flex items-center rounded-md border px-2.5 py-1 font-mono text-xs font-bold tracking-wider ${ACTION_STYLE[action]}`}>{action}{strength ? ` · ${strength}` : ""}</span>;
}

export function SignalCard({ analysis }: { analysis: Analysis }) {
  const s = analysis.signal;
  const pct = Math.round(((s.score + 100) / 200) * 100);
  const progress = Math.min(100, Math.round((analysis.bars_closed / analysis.bars_required) * 100));
  return (
    <div data-testid="signal-card" className={box}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Signal · {analysis.interval}-minute</p>
        <ActionPill action={s.action} strength={s.strength} />
      </div>
      {s.action === "BUILDING" ? (
        <div className="mt-3">
          <div className="h-2 overflow-hidden rounded-full bg-[#141c2b]"><div className="h-full rounded-full bg-sky-400 transition-all duration-700" style={{ width: `${progress}%` }} /></div>
          <p className="mt-2 text-[11px] text-slate-400">{analysis.bars_closed} of {analysis.bars_required} closed candles collected.</p>
        </div>
      ) : (
        <div className="mt-3">
          <div className="relative h-2 rounded-full bg-gradient-to-r from-rose-500/40 via-slate-600/40 to-emerald-500/40">
            <span className="absolute top-1/2 h-4 w-1.5 -translate-y-1/2 rounded-full bg-white shadow transition-all duration-700" style={{ left: `calc(${pct}% - 3px)` }} />
          </div>
          <div className="mt-1 flex justify-between text-[9px] text-slate-500"><span>Bearish -100</span><span data-testid="signal-score" className="font-mono text-slate-300">score {s.score > 0 ? "+" : ""}{s.score}</span><span>+100 Bullish</span></div>
        </div>
      )}
      <ul className="mt-3 space-y-1.5">
        {s.reasons.map((reason) => <li key={reason} className="text-[11px] leading-relaxed text-slate-400">• {reason}</li>)}
      </ul>
      <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">{analysis.disclaimer}</p>
    </div>
  );
}

export function TrendCard({ analysis }: { analysis: Analysis }) {
  const label = analysis.trend.label;
  const color = label === "UPTREND" ? "text-emerald-300" : label === "DOWNTREND" ? "text-rose-300" : label === "SIDEWAYS" ? "text-amber-300" : "text-sky-300";
  return (
    <div data-testid="trend-card" className={box}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Market trend</p>
      <p className={`mt-1 font-mono text-lg font-bold ${color}`}>{label}</p>
      <p className="mt-1 text-[11px] text-slate-500">{analysis.trend.basis.join(" · ") || "Needs more candles."}</p>
      <p className="mt-2 text-[11px] text-slate-500">ATR {price(analysis.atr)} · RSI {analysis.signal.rsi ?? "—"}</p>
    </div>
  );
}

export function LevelsCard({ analysis, last }: { analysis: Analysis; last: number | null }) {
  const lv = analysis.levels;
  const rows: { label: string; value: number | null; kind: "r" | "s" | "p" }[] = [];
  if (lv) {
    [...lv.resistance].reverse().forEach((v, i) => rows.push({ label: `Resistance ${lv.resistance.length - i}`, value: v, kind: "r" }));
    if (last !== null) rows.push({ label: "Last price", value: last, kind: "p" });
    lv.support.forEach((v, i) => rows.push({ label: `Support ${i + 1}`, value: v, kind: "s" }));
  }
  return (
    <div data-testid="levels-card" className={box}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Support and resistance</p>
      {rows.length === 0 ? (
        <p className="mt-2 text-[11px] text-slate-500">Levels appear once candles are collected.</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {rows.map((row) => (
            <li key={row.label} className="flex items-center justify-between text-[11px]">
              <span className={row.kind === "r" ? "text-rose-300/80" : row.kind === "s" ? "text-emerald-300/80" : "text-sky-300"}>{row.label}</span>
              <span className="font-mono tabular-nums text-slate-200">{price(row.value)}</span>
            </li>
          ))}
        </ul>
      )}
      {lv?.pivots ? (
        <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-500">Pivot {price(lv.pivots.pp)} · R1 {price(lv.pivots.r1)} · S1 {price(lv.pivots.s1)} (from the previous session)</p>
      ) : (
        <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">Pivot levels need one earlier recorded session. Levels shown come from today's swings and range.</p>
      )}
    </div>
  );
}

export function VolumeCard({ analysis }: { analysis: Analysis }) {
  const v = analysis.volume;
  return (
    <div data-testid="volume-card" className={box}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Volume analysis</p>
      {!v.available ? (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{v.note ?? "Volume is not available."}</p>
      ) : (
        <div className="mt-2 space-y-1.5 text-[11px]">
          <p className="flex justify-between"><span className="text-slate-500">Last candle</span><span className="font-mono text-slate-200">{whole(v.last)}</span></p>
          <p className="flex justify-between"><span className="text-slate-500">20-candle average</span><span className="font-mono text-slate-200">{whole(v.average_20)}</span></p>
          <p className="flex justify-between"><span className="text-slate-500">Relative volume</span><span className={`font-mono ${v.spike ? "text-amber-300" : "text-slate-200"}`}>{v.relative ?? "—"}x{v.spike ? " · spike" : ""}</span></p>
          <p className="flex justify-between"><span className="text-slate-500">Volume trend</span><span className="font-mono text-slate-200">{v.trend}</span></p>
          <div>
            <p className="flex justify-between"><span className="text-slate-500">Buying pressure</span><span className="font-mono text-slate-200">{v.buying_pressure_pct ?? "—"}%</span></p>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-rose-500/30"><div className="h-full rounded-full bg-emerald-400/80 transition-all duration-700" style={{ width: `${v.buying_pressure_pct ?? 0}%` }} /></div>
          </div>
        </div>
      )}
    </div>
  );
}
