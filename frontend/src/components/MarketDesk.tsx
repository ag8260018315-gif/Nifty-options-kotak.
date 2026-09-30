import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleHelp, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiGet } from "@/lib/api";

// Every number shown here comes from the backend. Missing values render as "—", never as a guess.

export type DeskSymbol = "NIFTY" | "BANKNIFTY" | "FINNIFTY";

export interface DeskSpot {
  ltp: number;
  change: number;
  pct_change: number;
  high: number;
  low: number;
  timestamp: string | null;
  open?: number | null;
  prev_close?: number | null;
}

export interface DeskLeg {
  ltp: number;
  change: number;
  oi: number;
  oi_change: number;
  iv: number;
  delta: number;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  volume?: number | null;
}

export interface DeskRow {
  strike: number;
  call: DeskLeg;
  put: DeskLeg;
  is_atm: boolean;
}

export interface DeskStructure {
  pcr: number;
  max_pain: number;
  bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  oi_buildup: string;
  total_call_oi?: number | null;
  total_put_oi?: number | null;
  window_strikes?: number | null;
  pcr_start?: number | null;
  pcr_start_at?: string | null;
}

interface TickerItem {
  symbol: DeskSymbol;
  name: string;
  available: boolean;
  state: string;
  ltp: number | null;
  change: number | null;
  pct_change: number | null;
  prev_close: number | null;
  last_tick: string | null;
}

interface TickerResponse {
  items: TickerItem[];
  delay_minutes: number;
  refresh_seconds: number;
}

const priceFormat = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integerFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const INDEX_NAMES: Record<DeskSymbol, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANKNIFTY", FINNIFTY: "FINNIFTY" };

function price(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : priceFormat.format(value);
}

function integer(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : integerFormat.format(value);
}

function signed(value: number, digits = 2) {
  const text = value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return value > 0 ? `+${text}` : text;
}

function clock(value: string | null | undefined, seconds = true) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: seconds ? "2-digit" : undefined, hour12: false, timeZone: "Asia/Kolkata" });
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

// Glides the displayed number to each new real value.
function useTweened(target: number | null, reduced: boolean) {
  const [value, setValue] = useState<number | null>(target);
  const current = useRef<number | null>(target);
  useEffect(() => {
    const from = current.current;
    if (target === null || from === null || reduced || from === target) {
      current.current = target;
      setValue(target);
      return;
    }
    const started = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / 600);
      const next = progress >= 1 ? target : from + (target - from) * (1 - Math.pow(1 - progress, 3));
      current.current = next;
      setValue(next);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, reduced]);
  return value;
}

function useTint(value: number | null) {
  const previous = useRef<number | null>(value);
  const [tint, setTint] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (value === null || before === null || value === before) return;
    setTint(value > before ? "up" : "down");
    const timer = window.setTimeout(() => setTint(null), 800);
    return () => window.clearTimeout(timer);
  }, [value]);
  return tint;
}

function Info({ text }: { text: string }) {
  return (
    <span title={text} aria-label={text} role="img" className="inline-flex cursor-help text-slate-600 hover:text-slate-400">
      <CircleHelp className="size-3" />
    </span>
  );
}

function StateDot({ state }: { state: string }) {
  if (state === "LIVE") {
    return (
      <span className="relative flex size-1.5" aria-hidden="true">
        <span className="absolute inline-flex size-full rounded-full bg-emerald-300 opacity-70 motion-safe:animate-ping" />
        <span className="relative inline-flex size-1.5 rounded-full bg-emerald-300" />
      </span>
    );
  }
  return <span aria-hidden="true" className={`size-1.5 rounded-full ${state === "STALE" ? "bg-amber-300" : "bg-slate-500"}`} />;
}

function stateText(state: string) {
  if (state === "LIVE") return "Live";
  if (state === "STALE") return "Data delayed";
  if (state === "MARKET_CLOSED") return "Market closed";
  if (state === "EXPIRED") return "Session expired";
  if (state === "DEMO") return "Demo";
  return "Unavailable";
}

// ------------------------------------------------------------------ section menu
const SECTIONS: { id: string; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "option-chain", label: "Option chain" },
  { id: "greeks", label: "Greeks" },
  { id: "signals", label: "Signals" },
  { id: "ai", label: "AI analyst" },
  { id: "export", label: "Export" },
];

export function DeskNav() {
  return (
    <nav aria-label="Dashboard sections" data-testid="desk-nav" className="-mx-1 flex gap-1 overflow-x-auto pb-1">
      {SECTIONS.map((section) => (
        <a key={section.id} href={`#${section.id}`} className="shrink-0 rounded-md px-3 py-1.5 text-xs text-slate-400 hover:bg-[#141c2b] hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">
          {section.label}
        </a>
      ))}
    </nav>
  );
}

// ------------------------------------------------------------------ live strip / index switcher
function TickerButton({ item, symbol, active, onSelect, reduced }: { item: TickerItem | undefined; symbol: DeskSymbol; active: boolean; onSelect: () => void; reduced: boolean }) {
  const ltp = item?.available ? item.ltp : null;
  const shown = useTweened(ltp, reduced);
  const tint = useTint(ltp);
  const change = item?.available ? item.change : null;
  const up = (change ?? 0) >= 0;
  const state = item?.state ?? "UNAVAILABLE";
  return (
    <button
      type="button"
      data-testid={`desk-ticker-${symbol}`}
      aria-pressed={active}
      onClick={onSelect}
      className={`min-w-[200px] flex-1 rounded-xl border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/50 ${active ? "border-blue-400/40 bg-[#131b2c]" : "border-[#202b42] bg-[#0c0f17]/90 hover:border-[#2c3a57]"}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`font-heading text-[13px] font-semibold ${active ? "text-white" : "text-slate-300"}`}>{INDEX_NAMES[symbol]}</span>
        <span className="flex items-center gap-1.5 text-[10px] text-slate-500"><StateDot state={state} />{stateText(state)}</span>
      </div>
      <div className="mt-1.5 flex items-baseline justify-between gap-3">
        <span className={`font-mono text-lg font-semibold tabular-nums transition-colors duration-700 ${tint === "up" ? "text-emerald-300" : tint === "down" ? "text-rose-300" : "text-slate-100"}`}>{shown === null ? "—" : price(shown)}</span>
        <span className={`font-mono text-[11px] tabular-nums ${change === null ? "text-slate-600" : up ? "text-emerald-400" : "text-rose-400"}`}>
          {change === null ? "Unavailable" : `${signed(change)}${item?.pct_change === null || item?.pct_change === undefined ? "" : ` (${signed(item.pct_change)}%)`}`}
        </span>
      </div>
    </button>
  );
}

export function MarketTicker({ active, onSelect }: { active: DeskSymbol; onSelect: (symbol: DeskSymbol) => void }) {
  const reduced = useReducedMotion();
  const ticker = useQuery({ queryKey: ["desk-ticker"], queryFn: () => apiGet<TickerResponse>("/public/ticker"), refetchInterval: 2000, retry: 1 });
  const items = ticker.data?.items ?? [];
  const latest = items.map((item) => item.last_tick).filter((value): value is string => Boolean(value)).sort().pop() ?? null;
  return (
    <section aria-label="Indices" data-testid="desk-ticker">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {(["NIFTY", "BANKNIFTY", "FINNIFTY"] as DeskSymbol[]).map((symbol) => (
          <TickerButton key={symbol} symbol={symbol} item={items.find((item) => item.symbol === symbol)} active={active === symbol} onSelect={() => onSelect(symbol)} reduced={reduced} />
        ))}
      </div>
      <p className="mt-1.5 text-[10px] text-slate-600">
        {ticker.isError ? "Index prices temporarily unavailable." : `Index prices update every ${ticker.data?.refresh_seconds ?? 2} s. Last update ${clock(latest)} IST.`} Select an index to switch the whole dashboard.
      </p>
    </section>
  );
}

// ------------------------------------------------------------------ index overview
export function IndexOverviewCard({ symbol, spot, hasTick, state, lastTick, atmStrike, expiry }: { symbol: DeskSymbol; spot: DeskSpot | undefined; hasTick: boolean; state: string; lastTick: string | null; atmStrike: number | null; expiry: string | undefined }) {
  const reduced = useReducedMotion();
  const ltp = spot && hasTick ? spot.ltp : null;
  const shown = useTweened(ltp, reduced);
  const tint = useTint(ltp);
  const up = (spot?.change ?? 0) >= 0;
  const cells: { label: string; value: string }[] = [
    { label: "Open", value: hasTick ? price(spot?.open) : "—" },
    { label: "Previous close", value: hasTick ? price(spot?.prev_close) : "—" },
    { label: "High", value: hasTick ? price(spot?.high) : "—" },
    { label: "Low", value: hasTick ? price(spot?.low) : "—" },
    { label: "ATM strike", value: hasTick && atmStrike !== null ? integer(atmStrike) : "—" },
    { label: "Expiry", value: expiry ?? "—" },
  ];
  return (
    <Card data-testid="index-overview-card" className="border-[#202b42] bg-[#101621]/90 sm:col-span-2">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-heading text-sm font-semibold text-slate-200">{INDEX_NAMES[symbol]}</p>
            <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500"><StateDot state={state} />{stateText(state)}{state === "MARKET_CLOSED" ? ". Showing latest available data" : ""}</p>
          </div>
          <p className="text-right text-[10px] text-slate-500">Updated<br /><span className="font-mono text-slate-400">{clock(lastTick)} IST</span></p>
        </div>
        <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <p data-testid="ticker-spot-price" className={`font-mono text-[32px] font-bold leading-none tabular-nums tracking-tight transition-colors duration-700 ${tint === "up" ? "text-emerald-300" : tint === "down" ? "text-rose-300" : "text-white"}`}>{shown === null ? "—" : price(shown)}</p>
          <p data-testid="ticker-day-change" className={`font-mono text-sm font-semibold tabular-nums ${!spot || !hasTick ? "text-slate-500" : up ? "text-emerald-400" : "text-rose-400"}`}>
            {spot && hasTick ? `${up ? "▲" : "▼"} ${signed(spot.change)} (${signed(spot.pct_change)}%)` : "Waiting for the first Kotak tick"}
          </p>
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-[#202b42] pt-4 sm:grid-cols-3">
          {cells.map((cell) => (
            <div key={cell.label}>
              <dt className="text-[10px] text-slate-500">{cell.label}</dt>
              <dd className="mt-0.5 font-mono text-[13px] tabular-nums text-slate-200">{cell.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ PCR / OI
export function PcrOiCard({ structure, rows, hasChain }: { structure: DeskStructure | undefined; rows: DeskRow[]; hasChain: boolean }) {
  const callOi = structure?.total_call_oi ?? (rows.length ? rows.reduce((sum, row) => sum + row.call.oi, 0) : null);
  const putOi = structure?.total_put_oi ?? (rows.length ? rows.reduce((sum, row) => sum + row.put.oi, 0) : null);
  const pcr = hasChain && structure ? structure.pcr : null;
  const pcrMove = pcr !== null && structure?.pcr_start !== null && structure?.pcr_start !== undefined ? pcr - structure.pcr_start : null;
  const putShare = callOi !== null && putOi !== null && callOi + putOi > 0 ? putOi / (callOi + putOi) : null;
  const topCall = rows.length ? rows.reduce((best, row) => (row.call.oi > best.call.oi ? row : best)) : null;
  const topPut = rows.length ? rows.reduce((best, row) => (row.put.oi > best.put.oi ? row : best)) : null;
  const reading = pcr === null ? null : pcr >= 1.05 ? "Put open interest is heavier than call open interest across these strikes." : pcr <= 0.85 ? "Call open interest is heavier than put open interest across these strikes." : "Call and put open interest are fairly balanced across these strikes.";
  return (
    <Card data-testid="pcr-oi-card" className="border-[#202b42] bg-[#101621]/90">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <p className="flex items-center gap-1.5 text-[11px] text-slate-400">Put/call ratio <Info text="Put-call ratio compares put open interest with call open interest for the strikes shown." /></p>
          {pcrMove !== null && <span className={`font-mono text-[11px] ${pcrMove >= 0 ? "text-emerald-400" : "text-rose-400"}`} title={`Since ${clock(structure?.pcr_start_at, false)} IST`}>{signed(pcrMove)} today</span>}
        </div>
        <p data-testid="pcr-gauge-value" className="mt-1.5 font-mono text-[28px] font-bold leading-none tabular-nums text-white">{pcr === null ? "—" : pcr.toFixed(2)}</p>
        <div className="mt-4" aria-hidden={putShare === null}>
          <div className="flex h-1.5 overflow-hidden rounded-full bg-[#202b42]">
            {putShare !== null && (
              <>
                <div className="bg-emerald-400/70 transition-[width] duration-700" style={{ width: `${(1 - putShare) * 100}%` }} />
                <div className="bg-rose-400/70 transition-[width] duration-700" style={{ width: `${putShare * 100}%` }} />
              </>
            )}
          </div>
          <div className="mt-1.5 flex justify-between font-mono text-[10px] tabular-nums">
            <span className="text-emerald-300/80">Calls {integer(callOi)}</span>
            <span className="text-rose-300/80">Puts {integer(putOi)}</span>
          </div>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
          <div><dt className="text-slate-500">Most call OI</dt><dd className="font-mono text-slate-200">{topCall && hasChain ? integer(topCall.strike) : "—"}</dd></div>
          <div><dt className="text-slate-500">Most put OI</dt><dd className="font-mono text-slate-200">{topPut && hasChain ? integer(topPut.strike) : "—"}</dd></div>
        </dl>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-400">{reading ? `${reading} This describes positioning, not direction.` : "Waiting for the option chain."}</p>
        {structure?.window_strikes ? <p className="mt-1 text-[10px] text-slate-600">Totals cover the {structure.window_strikes} strikes around ATM, not the full chain.</p> : null}
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ option chain
type ChainView = "expanded" | "compact";

export function OptionChainTable({ symbol, rows, allRows, spot, expiry, range, onRange, onExport, canExport, exporting, footnote, asOf }: {
  symbol: DeskSymbol;
  rows: DeskRow[];
  allRows: DeskRow[];
  spot: number | null;
  expiry: string | undefined;
  range: string;
  onRange: (value: string) => void;
  onExport: () => void;
  canExport: boolean;
  exporting: boolean;
  footnote: string;
  asOf: string | null;
}) {
  const [view, setView] = useState<ChainView>("expanded");
  const [search, setSearch] = useState("");
  const digits = search.replace(/\D/g, "");
  const shown = digits ? allRows.filter((row) => String(row.strike).includes(digits)) : rows;
  const marks = useMemo(() => {
    if (!allRows.length) return { call: null as number | null, put: null as number | null, change: null as number | null };
    const call = allRows.reduce((best, row) => (row.call.oi > best.call.oi ? row : best)).strike;
    const put = allRows.reduce((best, row) => (row.put.oi > best.put.oi ? row : best)).strike;
    let change: number | null = null;
    let biggest = 0;
    for (const row of allRows) {
      for (const leg of [row.call, row.put]) {
        if (Math.abs(leg.oi_change) > biggest) {
          biggest = Math.abs(leg.oi_change);
          change = row.strike;
        }
      }
    }
    return { call, put, change };
  }, [allRows]);
  const expanded = view === "expanded";
  const head = "sticky top-0 z-10 bg-[#0e131d] px-2 py-2 font-medium";
  const oiChange = (value: number) => <span className={value >= 0 ? "text-emerald-400" : "text-rose-400"}>{value >= 0 ? "+" : ""}{integer(value)}</span>;
  return (
    <Card data-testid="option-chain-container" className="overflow-hidden border-[#202b42] bg-[#0c0f17]/95 shadow-[0_20px_50px_rgba(0,0,0,0.18)]">
      <CardHeader className="border-b border-[#202b42] px-4 py-3 sm:px-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle data-testid="option-chain-title" className="font-heading text-base text-slate-100">{INDEX_NAMES[symbol]} option chain</CardTitle>
            <p className="mt-1 text-xs text-slate-500">Calls on the left, puts on the right. Shaded cells are in the money.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="strike-search" className="sr-only">Find a strike</label>
            <input id="strike-search" data-testid="strike-search" inputMode="numeric" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find strike" className="h-8 w-28 rounded-md border border-[#2a364f] bg-[#111622] px-2.5 text-[11px] text-slate-200 placeholder:text-slate-600 outline-none focus:border-blue-500" />
            <div role="group" aria-label="Table density" className="flex rounded-md border border-[#2a364f] p-0.5">
              {(["expanded", "compact"] as ChainView[]).map((option) => (
                <button key={option} type="button" aria-pressed={view === option} onClick={() => setView(option)} className={`rounded px-2 py-1 text-[11px] capitalize ${view === option ? "bg-[#1f2a41] text-white" : "text-slate-400 hover:text-slate-200"}`}>{option}</button>
              ))}
            </div>
            <label htmlFor="strike-filter-range" className="sr-only">Strike range</label>
            <select id="strike-filter-range" data-testid="strike-filter-range" value={range} onChange={(event) => onRange(event.target.value)} className="h-8 rounded-md border border-[#2a364f] bg-[#111622] px-2 text-[11px] text-slate-300 outline-none focus:border-blue-500"><option value="3">±3 strikes</option><option value="5">±5 strikes</option><option value="10">±10 strikes</option></select>
            <label htmlFor="expiry-date-select" className="sr-only">Expiry</label>
            <select id="expiry-date-select" data-testid="expiry-date-select" defaultValue="current" title="The feed follows the nearest expiry" className="h-8 rounded-md border border-[#2a364f] bg-[#111622] px-2 text-[11px] text-slate-300 outline-none focus:border-blue-500"><option value="current">{expiry ?? "Current expiry"}</option></select>
            <Button data-testid="export-csv-button" type="button" variant="outline" size="sm" className="h-8 border-emerald-500/25 bg-emerald-500/5 text-[11px] text-emerald-300 hover:bg-emerald-500/10" disabled={!canExport || exporting} title={canExport ? `Export today's verified ${symbol} snapshots` : "Available after the first verified Kotak option snapshot"} onClick={onExport}>
              <Download className="mr-1.5 size-3.5" />{exporting ? "Preparing…" : "Export CSV"}
            </Button>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
          <span>Most call OI <span className="font-mono text-emerald-300">{marks.call ?? "—"}</span></span>
          <span>Most put OI <span className="font-mono text-rose-300">{marks.put ?? "—"}</span></span>
          <span>Biggest OI change <span className="font-mono text-amber-300">{marks.change ?? "—"}</span></span>
          <span>Spot <span className="font-mono text-slate-300">{price(spot)}</span></span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="max-h-[620px] overflow-auto">
          <table className={`w-full border-collapse text-right text-xs ${expanded ? "min-w-[980px]" : "min-w-[560px]"}`}>
            <thead data-testid="option-chain-table-head" className="text-[10px] text-slate-500">
              <tr>
                <th className={`${head} text-left`}>OI</th>
                <th className={head}>OI chg</th>
                {expanded && <th className={head}>Volume</th>}
                {expanded && <th className={head}><span className="inline-flex items-center gap-1">IV <Info text="Implied volatility reflects the volatility level implied by the option's price. Model estimate." /></span></th>}
                {expanded && <th className={head}><span className="inline-flex items-center gap-1">Delta <Info text="How much the option's price may change for a one-point index move, all else equal. Model estimate." /></span></th>}
                <th className={`${head} text-emerald-300/80`}>Call LTP</th>
                <th className={`${head} bg-[#141c2b] text-center text-blue-300`}>Strike</th>
                <th className={`${head} text-left text-rose-300/80`}>Put LTP</th>
                {expanded && <th className={`${head} text-left`}>Delta</th>}
                {expanded && <th className={`${head} text-left`}>IV</th>}
                {expanded && <th className={`${head} text-left`}>Volume</th>}
                <th className={`${head} text-left`}>OI chg</th>
                <th className={head}>OI</th>
              </tr>
            </thead>
            <tbody data-testid="option-chain-table-body" className="font-mono tabular-nums">
              {shown.map((row) => {
                const callItm = spot !== null && row.strike < spot;
                const putItm = spot !== null && row.strike > spot;
                const callCell = callItm ? "bg-emerald-500/[0.045]" : "";
                const putCell = putItm ? "bg-rose-500/[0.045]" : "";
                return (
                  <tr key={row.strike} data-testid={`option-chain-row-${row.strike}`} className={`border-t border-[#182134] transition-colors hover:bg-[#162033] ${row.is_atm ? "bg-[#1b263a]" : ""}`}>
                    <td className={`px-2 py-2.5 text-left text-slate-300 ${callCell}`}>{integer(row.call.oi)}{marks.call === row.strike && <span className="ml-1 rounded bg-emerald-500/15 px-1 text-[9px] text-emerald-300">max</span>}</td>
                    <td className={`px-2 py-2.5 ${callCell} ${marks.change === row.strike ? "font-semibold" : ""}`}>{oiChange(row.call.oi_change)}</td>
                    {expanded && <td className={`px-2 py-2.5 text-slate-400 ${callCell}`}>{integer(row.call.volume)}</td>}
                    {expanded && <td className={`px-2 py-2.5 text-slate-400 ${callCell}`}>{row.call.iv ? `${row.call.iv.toFixed(1)}%` : "—"}</td>}
                    {expanded && <td className={`px-2 py-2.5 text-emerald-300/90 ${callCell}`}>{row.call.delta.toFixed(2)}</td>}
                    <td data-testid={`call-ltp-cell-${row.strike}`} className={`px-2 py-2.5 font-semibold text-emerald-300 ${callCell}`}>{price(row.call.ltp)}</td>
                    <td data-testid={`strike-cell-${row.strike}`} className={`bg-[#141c2b] px-3 py-2.5 text-center font-semibold ${row.is_atm ? "text-blue-200" : "text-slate-100"}`}>
                      {row.strike}
                      {row.is_atm && <span data-testid={`atm-marker-${row.strike}`} className="ml-1.5 rounded bg-blue-500/20 px-1 py-px text-[9px] text-blue-200">ATM</span>}
                    </td>
                    <td data-testid={`put-ltp-cell-${row.strike}`} className={`px-2 py-2.5 text-left font-semibold text-rose-300 ${putCell}`}>{price(row.put.ltp)}</td>
                    {expanded && <td className={`px-2 py-2.5 text-left text-rose-300/90 ${putCell}`}>{row.put.delta.toFixed(2)}</td>}
                    {expanded && <td className={`px-2 py-2.5 text-left text-slate-400 ${putCell}`}>{row.put.iv ? `${row.put.iv.toFixed(1)}%` : "—"}</td>}
                    {expanded && <td className={`px-2 py-2.5 text-left text-slate-400 ${putCell}`}>{integer(row.put.volume)}</td>}
                    <td className={`px-2 py-2.5 text-left ${putCell} ${marks.change === row.strike ? "font-semibold" : ""}`}>{oiChange(row.put.oi_change)}</td>
                    <td className={`px-2 py-2.5 text-slate-300 ${putCell}`}>{marks.put === row.strike && <span className="mr-1 rounded bg-rose-500/15 px-1 text-[9px] text-rose-300">max</span>}{integer(row.put.oi)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {shown.length === 0 && <p className="px-4 py-8 text-center text-xs text-slate-500">{digits ? `No strike matching ${digits} in the current window.` : "Waiting for live option ticks."}</p>}
        </div>
        <div data-testid="option-chain-footnote" className="flex flex-wrap items-center justify-between gap-2 border-t border-[#202b42] px-4 py-3 text-[10px] text-slate-500">
          <span>{footnote}</span>
          <span className="font-mono tabular-nums">as of {asOf ? clock(asOf) : "—"}</span>
        </div>
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ Greeks ladder
const GREEK_HELP = {
  iv: "Implied volatility reflects the volatility level implied by the option's price.",
  delta: "How much the option's price may change for a one-point index move, all else equal.",
  gamma: "How quickly delta changes as the index moves.",
  theta: "Estimated time decay of the option, in rupees per day.",
  vega: "Estimated price change for a one-point change in implied volatility.",
};

export function GreeksLadder({ rows, spot }: { rows: DeskRow[]; spot: number | null }) {
  const [side, setSide] = useState<"CE" | "PE">("CE");
  const head = "px-3 py-2 font-medium";
  return (
    <Card data-testid="greeks-ladder" className="overflow-hidden border-[#202b42] bg-[#0c0f17]/95">
      <CardHeader className="border-b border-[#202b42] px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="font-heading text-base text-slate-100">Greeks ladder</CardTitle>
            <p className="mt-1 text-xs text-slate-500">Model estimates from live option prices (Black-Scholes), not exchange figures.</p>
          </div>
          <div role="group" aria-label="Option side" className="flex rounded-md border border-[#2a364f] p-0.5">
            {(["CE", "PE"] as const).map((option) => (
              <button key={option} type="button" aria-pressed={side === option} data-testid={`greeks-side-${option}`} onClick={() => setSide(option)} className={`rounded px-3 py-1 text-[11px] font-semibold ${side === option ? (option === "CE" ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300") : "text-slate-400 hover:text-slate-200"}`}>
                {option === "CE" ? "Calls" : "Puts"}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] border-collapse text-right text-xs">
            <thead className="bg-[#0e131d] text-[10px] text-slate-500">
              <tr>
                <th className={`${head} text-left`}>Strike</th>
                <th className={head}><span className="inline-flex items-center gap-1">IV <Info text={GREEK_HELP.iv} /></span></th>
                <th className={`${head} text-left`}><span className="inline-flex items-center gap-1">Delta <Info text={GREEK_HELP.delta} /></span></th>
                <th className={head}><span className="inline-flex items-center gap-1">Gamma <Info text={GREEK_HELP.gamma} /></span></th>
                <th className={head}><span className="inline-flex items-center gap-1">Theta / day <Info text={GREEK_HELP.theta} /></span></th>
                <th className={head}><span className="inline-flex items-center gap-1">Vega <Info text={GREEK_HELP.vega} /></span></th>
              </tr>
            </thead>
            <tbody key={side} className="font-mono tabular-nums motion-safe:animate-in motion-safe:fade-in-0">
              {rows.map((row) => {
                const leg = side === "CE" ? row.call : row.put;
                const itm = spot !== null && (side === "CE" ? row.strike < spot : row.strike > spot);
                const tag = row.is_atm ? "ATM" : itm ? "ITM" : "OTM";
                const deltaWidth = Math.min(100, Math.abs(leg.delta) * 100);
                return (
                  <tr key={row.strike} className={`border-t border-[#182134] ${row.is_atm ? "bg-[#1b263a]" : "hover:bg-[#121a29]"}`}>
                    <td className="px-3 py-2.5 text-left">
                      <span className="font-semibold text-slate-100">{row.strike}</span>
                      <span className={`ml-2 rounded px-1 py-px text-[9px] ${tag === "ATM" ? "bg-blue-500/20 text-blue-200" : tag === "ITM" ? "bg-slate-500/20 text-slate-300" : "text-slate-600"}`}>{tag}</span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-300">{leg.iv ? `${leg.iv.toFixed(1)}%` : "—"}</td>
                    <td className="px-3 py-2.5 text-left">
                      <div className="flex items-center gap-2">
                        <span className="w-12 text-slate-200">{leg.delta.toFixed(2)}</span>
                        <span className="h-1 w-20 overflow-hidden rounded-full bg-[#202b42]"><span className={`block h-full rounded-full transition-[width] duration-500 ${side === "CE" ? "bg-emerald-400/70" : "bg-rose-400/70"}`} style={{ width: `${deltaWidth}%` }} /></span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-slate-300">{leg.gamma === null || leg.gamma === undefined ? "—" : leg.gamma.toFixed(5)}</td>
                    <td className="px-3 py-2.5 text-slate-300">{leg.theta === null || leg.theta === undefined ? "—" : leg.theta.toFixed(2)}</td>
                    <td className="px-3 py-2.5 text-slate-300">{leg.vega === null || leg.vega === undefined ? "—" : leg.vega.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <p className="px-4 py-8 text-center text-xs text-slate-500">Waiting for live option ticks.</p>}
        </div>
        <p className="border-t border-[#202b42] px-4 py-2.5 text-[10px] text-slate-600">A dash means the model couldn't estimate that value from the current price, so none is shown.</p>
      </CardContent>
    </Card>
  );
}
