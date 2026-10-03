import { useState } from "react";

import { clockTime, intervalName, price, signed, stamp, tickAge, tone, whole, type Analysis, type Bias, type DataStatus, type EngineSignal, type Performance, type PerformanceStats, type TradeSetup } from "@/lib/premium";

const box = "rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3";
const label = "text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500";

const BIAS_STYLE: Record<Bias, string> = {
  Bullish: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  Bearish: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  Neutral: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  Unavailable: "border-sky-500/30 bg-sky-500/10 text-sky-300",
};

export function BiasPill({ bias, large = false }: { bias: Bias; large?: boolean }) {
  return <span data-testid="bias-pill" className={`inline-flex items-center rounded-md border font-mono font-bold tracking-normal sm:tracking-wider ${large ? "px-3.5 py-1.5 text-base" : "px-2 py-0.5 text-[10px] sm:px-2.5 sm:py-1 sm:text-xs"} ${BIAS_STYLE[bias]}`}>{bias === "Unavailable" ? "NO SIGNAL" : bias.toUpperCase()}</span>;
}

const DATA_STYLE: Record<DataStatus, string> = {
  LIVE: "border-emerald-500/35 bg-emerald-950/70 text-emerald-300",
  HISTORICAL: "border-zinc-600/60 bg-zinc-900/90 text-zinc-300",
  DELAYED: "border-amber-500/35 bg-amber-950/70 text-amber-300",
  UNAVAILABLE: "border-rose-500/35 bg-rose-950/70 text-rose-300",
};

// Says where the numbers come from: live ticks, the last finished session, delayed, or not available at all.
export function DataBadge({ data }: { data: EngineSignal["data"] }) {
  return (
    <span data-testid="data-badge" title={data.message} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold tracking-[0.12em] ${DATA_STYLE[data.status]}`}>
      <span className={`size-1.5 rounded-full ${data.status === "LIVE" ? "animate-pulse bg-emerald-400" : data.status === "DELAYED" ? "bg-amber-400" : data.status === "UNAVAILABLE" ? "bg-rose-400" : "bg-zinc-500"}`} />
      {data.status === "HISTORICAL" ? "LAST SESSION" : data.status}
    </span>
  );
}

function Meter({ value, text, from = 0, to = 100, centered = false, testId }: { value: number | null; text: string; from?: number; to?: number; centered?: boolean; testId: string }) {
  const pct = value === null ? 0 : Math.max(0, Math.min(100, ((value - from) / (to - from)) * 100));
  return (
    <div data-testid={testId}>
      <div className="relative h-1.5 overflow-hidden rounded-full bg-[#141c2b]">
        {centered ? (
          <div className={`absolute top-0 h-full ${value !== null && value < 0 ? "bg-rose-400/80" : "bg-emerald-400/80"}`} style={{ left: value !== null && value < 0 ? `${pct}%` : "50%", width: `${Math.abs(pct - 50)}%` }} />
        ) : (
          <div className="h-full rounded-full bg-sky-400/80 transition-all duration-700" style={{ width: `${pct}%` }} />
        )}
      </div>
      <p className="mt-1 text-[11px] text-slate-300">{text}</p>
    </div>
  );
}

function strength(value: number | null): string {
  return value === null ? "Unknown" : value >= 66 ? "Strong" : value >= 33 ? "Moderate" : "Weak";
}

export function EngineCard({ engine, analysis }: { engine: EngineSignal; analysis: Analysis }) {
  const building = analysis.signal.action === "BUILDING";
  const progress = Math.min(100, Math.round((analysis.bars_closed / analysis.bars_required) * 100));
  const none = engine.bias === "Unavailable";
  return (
    <div data-testid="engine-card" className={box}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={label}>Signal engine · {intervalName(engine.interval)}</p>
        <DataBadge data={engine.data} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <BiasPill bias={engine.bias} large />
        {!none && (
          <div data-testid="engine-confidence" className="min-w-0">
            <p className="font-mono text-sm font-semibold text-slate-100">Confidence {engine.confidence.value}/100</p>
            <p className="max-w-[16rem] text-[10px] leading-snug text-slate-500">{engine.confidence.meaning}</p>
          </div>
        )}
      </div>
      {building && (
        <div className="mt-3">
          <div className="h-2 overflow-hidden rounded-full bg-[#141c2b]"><div className="h-full rounded-full bg-sky-400 transition-all duration-700" style={{ width: `${progress}%` }} /></div>
          <p className="mt-2 text-[11px] text-slate-400">{analysis.bars_closed} of {analysis.bars_required} closed candles collected. A signal needs {analysis.bars_required}.</p>
        </div>
      )}
      {!none && (
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Trend strength</dt>
            <dd><Meter testId="meter-trend" value={engine.trend_strength} text={`${strength(engine.trend_strength)}${engine.trend_strength === null ? "" : ` · ${engine.trend_strength}`}`} /></dd>
          </div>
          <div>
            <dt className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Momentum</dt>
            <dd><Meter testId="meter-momentum" centered from={-100} to={100} value={engine.momentum?.value ?? null} text={engine.momentum ? `${engine.momentum.label} (${engine.momentum.value > 0 ? "+" : ""}${engine.momentum.value})` : "Unknown"} /></dd>
          </div>
          <div>
            <dt className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Volatility</dt>
            <dd data-testid="meter-volatility" className="text-[11px] text-slate-300">{engine.volatility?.label ?? "Unknown"}{engine.volatility?.atr_pct != null ? ` · ATR ${engine.volatility.atr_pct}% of price` : ""}</dd>
          </div>
        </dl>
      )}
      <ul className="mt-3 space-y-1.5">
        {engine.reasons.map((reason, i) => <li key={`${i}-${reason}`} className="text-[11px] leading-relaxed text-slate-400">• {reason}</li>)}
      </ul>
      <p data-testid="engine-generated" className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-500">
        Generated {clockTime(engine.generated_at)}
        {engine.as_of_candle ? ` · based on the ${stamp(engine.as_of_candle, engine.interval)} candle (closed candles only)` : ""}
        {` · latest price ${tickAge(engine.data.tick_age_seconds)}`}
      </p>
      <p className="mt-1 text-[10px] leading-relaxed text-slate-600">{engine.disclaimer}</p>
    </div>
  );
}

function pct(from: number, to: number): string {
  return `${signed(((to - from) / from) * 100, "%")}`;
}

// The setup is drawn from the last CLOSED candle, so on longer timeframes the live price can have moved well away from it.
// Say where the price stands now instead of leaving the reader to compare numbers.
function standing(s: TradeSetup, last: number | null): { text: string; tone: "good" | "bad" | "warn" } | null {
  if (last === null) return null;
  const long = s.direction === "LONG";
  if (long ? last <= s.stop : last >= s.stop) return { text: "Price is at or beyond the stop level, so this setup has failed.", tone: "bad" };
  if (long ? last >= s.targets[0] : last <= s.targets[0]) return { text: "Price has already reached target 1, so this setup has played out.", tone: "good" };
  if (last >= s.entry_zone[0] && last <= s.entry_zone[1]) return { text: `Price is inside the ${s.zone_label.toLowerCase()} now.`, tone: "good" };
  const away = Math.abs(((last - s.entry) / s.entry) * 100).toFixed(2);
  return { text: `Price is ${away}% ${last > s.entry_zone[1] ? "above" : "below"} the ${s.zone_label.toLowerCase()}, so entering now has a different risk and reward than shown.`, tone: "warn" };
}

export function SetupCard({ engine, last = null }: { engine: EngineSignal; last?: number | null }) {
  const s = engine.setup;
  const long = s?.direction === "LONG";
  const where = s ? standing(s, last) : null;
  return (
    <div data-testid="setup-card" className={box}>
      <div className="flex items-center justify-between gap-2">
        <p className={label}>Trade setup (informational)</p>
        {s && <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold ${long ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-rose-500/40 bg-rose-500/10 text-rose-300"}`}>{s.zone_label.toUpperCase()}</span>}
      </div>
      {!s ? (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">No setup. The engine is {engine.bias === "Unavailable" ? "not producing a signal right now" : "Neutral"}, so no entry, stop or targets are suggested.</p>
      ) : (
        <>
          {where && <p data-testid="setup-standing" className={`mt-3 rounded-md border px-2.5 py-1.5 text-[11px] leading-snug ${where.tone === "good" ? "border-emerald-500/30 bg-emerald-500/[0.07] text-emerald-200" : where.tone === "bad" ? "border-rose-500/30 bg-rose-500/[0.07] text-rose-200" : "border-amber-400/30 bg-amber-400/[0.07] text-amber-200"}`}>{where.text}</p>}
          <dl className="mt-3 space-y-1.5 text-[11px]">
            <div className="flex justify-between"><dt className="text-slate-500">{s.zone_label}</dt><dd data-testid="setup-zone" className="font-mono tabular-nums text-slate-200">{price(s.entry_zone[0])} – {price(s.entry_zone[1])}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Entry (last close)</dt><dd data-testid="setup-entry" className="font-mono tabular-nums text-sky-300">{price(s.entry)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Stop</dt><dd data-testid="setup-stop" className="font-mono tabular-nums text-rose-300">{price(s.stop)} <span className="text-slate-500">({pct(s.entry, s.stop)})</span></dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Target 1</dt><dd data-testid="setup-t1" className="font-mono tabular-nums text-emerald-300">{price(s.targets[0])} <span className="text-slate-500">({pct(s.entry, s.targets[0])} · {s.reward_to_risk}R)</span></dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Target 2</dt><dd className="font-mono tabular-nums text-emerald-200">{price(s.targets[1])} <span className="text-slate-500">({pct(s.entry, s.targets[1])} · {(Math.abs(s.targets[1] - s.entry) / s.risk_per_share).toFixed(1)}R)</span></dd></div>
            <div className="flex justify-between border-t border-[#202b42] pt-1.5"><dt className="text-slate-500">Risk per share</dt><dd className="font-mono tabular-nums text-slate-200">{price(s.risk_per_share)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Reward-to-risk</dt><dd data-testid="setup-rr" className="font-mono tabular-nums text-slate-100">1 : {s.reward_to_risk}</dd></div>
          </dl>
          <p className="mt-2 text-[10px] leading-relaxed text-slate-600">{s.method}</p>
        </>
      )}
      <div className="mt-3 border-t border-[#202b42] pt-2">
        <p className={label}>What would invalidate it</p>
        <ul data-testid="engine-invalidation" className="mt-1.5 space-y-1">
          {engine.invalidation.length === 0 ? <li className="text-[11px] text-slate-500">Nothing to invalidate while there is no signal.</li> : engine.invalidation.map((line, i) => <li key={`${i}-${line}`} className="text-[11px] leading-relaxed text-slate-400">• {line}</li>)}
        </ul>
      </div>
    </div>
  );
}

export function PatternsCard({ engine, interval }: { engine: EngineSignal; interval: number }) {
  const hits = [...(engine.markers ?? [])].sort((a, b) => b.time - a.time).slice(0, 8);
  return (
    <div data-testid="patterns-card" className={box}>
      <p className={label}>Candlestick patterns · last 30 candles</p>
      {hits.length === 0 ? (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{engine.bias === "Unavailable" ? "Patterns need a working signal and enough closed candles." : "No pattern found in the recent closed candles."}</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {hits.map((hit) => (
            <li key={`${hit.time}-${hit.name}`}>
              <p className="flex items-center gap-2 text-[11px]">
                <span className={hit.direction === "bullish" ? "text-emerald-300" : hit.direction === "bearish" ? "text-rose-300" : "text-violet-300"}>{hit.direction === "bullish" ? "▲" : hit.direction === "bearish" ? "▼" : "◆"}</span>
                <span className="font-semibold text-slate-200">{hit.name}</span>
                <span className="text-slate-500">{stamp(hit.time, interval)}</span>
              </p>
              <p className="ml-5 text-[10px] leading-snug text-slate-500">{hit.explanation}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">Patterns are context. At most ±12 points are added to the score for the last 3 candles; a pattern alone never creates a signal.</p>
    </div>
  );
}

function ratePct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

function Stats({ stats, testId }: { stats: PerformanceStats; testId: string }) {
  if (!stats.trades) return <p className="mt-2 text-[11px] text-slate-500">{stats.note}</p>;
  const range = stats.win_rate_ci95_pct;
  return (
    <div data-testid={testId} className="mt-2 space-y-2">
      <p className="text-[11px] leading-relaxed text-slate-300">
        <span className="font-mono text-base font-bold text-white">{ratePct(stats.win_rate_pct)}</span> of {whole(stats.trades)} past trades ended in profit after costs
        {range ? <span className="text-slate-500"> (likely range {range[0]}–{range[1]}%)</span> : null}
        {stats.period ? <span className="text-slate-500"> · {stats.period[0]} to {stats.period[1]}</span> : null}
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] sm:grid-cols-4">
        <div><dt className="text-slate-500">Average result</dt><dd className={`font-mono tabular-nums ${tone(stats.avg_r)}`}>{signed(stats.avg_r, "R")}</dd></div>
        <div><dt className="text-slate-500">Profit factor</dt><dd className="font-mono tabular-nums text-slate-200">{stats.profit_factor ?? "—"}</dd></div>
        <div><dt className="text-slate-500">Worst drawdown</dt><dd className="font-mono tabular-nums text-rose-300">{stats.max_drawdown_r === undefined ? "—" : `-${stats.max_drawdown_r}R`}</dd></div>
        <div><dt className="text-slate-500">Longest losing run</dt><dd className="font-mono tabular-nums text-slate-200">{stats.longest_losing_streak ?? "—"} trades</dd></div>
      </dl>
      {stats.by_direction && (
        <p className="text-[10px] text-slate-500">Buy setups: {ratePct(stats.by_direction.LONG.win_rate_pct)} of {stats.by_direction.LONG.trades} · Sell setups: {ratePct(stats.by_direction.SHORT.win_rate_pct)} of {stats.by_direction.SHORT.trades}</p>
      )}
      <p className={`text-[10px] ${stats.reliable ? "text-slate-500" : "text-amber-300"}`}>{stats.note}</p>
    </div>
  );
}

// Past results of the exact rule the engine uses, from stored history. Never a forecast, and never shown unless it was really tested.
export function PerformanceCard({ performance, name }: { performance: Performance; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="performance-card" className={box}>
      <div className="flex items-center justify-between gap-2">
        <p className={label}>Tested history of this rule</p>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${performance.tested ? "border-sky-400/30 bg-sky-400/10 text-sky-200" : "border-zinc-600/60 bg-zinc-900/80 text-zinc-300"}`}>{performance.tested ? "PAST DATA" : "NOT TESTED"}</span>
      </div>
      {performance.tested ? (
        <Stats stats={performance as PerformanceStats} testId="performance-stock" />
      ) : (
        <p data-testid="performance-untested" className="mt-2 text-[11px] leading-relaxed text-slate-400">{performance.note ?? "No tested history exists for this stock yet."} No win rate is shown for {name} because none has been measured.</p>
      )}
      {performance.overall && performance.overall.trades ? (
        <div className="mt-3 border-t border-[#202b42] pt-2">
          <p className={label}>All tested stocks together</p>
          <Stats stats={performance.overall} testId="performance-overall" />
        </div>
      ) : null}
      <button type="button" data-testid="performance-how" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="mt-3 text-[10px] text-sky-300 underline-offset-2 hover:underline">{open ? "Hide" : "How this was tested"}</button>
      {open && (
        <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
          {performance.definition ?? performance.overall?.definition ?? "The back-test replays stored 1-minute candles through the same engine. Each decision uses only candles that had already closed; the outcome comes only from later candles."}
          {performance.rule ? ` Time limit ${performance.rule.horizon_minutes} minutes, a cost of ${performance.rule.cost_pct}% per round trip, one trade at a time.` : ""} R is the amount risked on a trade: +1.5R means a gain of one and a half times the risk. Results describe the past and are not a promise.
        </p>
      )}
    </div>
  );
}
