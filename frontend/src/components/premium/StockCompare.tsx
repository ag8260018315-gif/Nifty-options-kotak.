import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { MarketBadge } from "@/components/premium/AnalysisPanels";
import { BiasPill, DataBadge } from "@/components/premium/StockPanels";
import { apiGet } from "@/lib/api";
import { INTERVAL_OPTIONS, intervalName, price, signed, stamp, tone, whole, type CompareResponse, type Interval } from "@/lib/premium";
import { keepPreviousData, useStocksMeta } from "@/lib/premiumData";

const COLORS = ["#38bdf8", "#fbbf24", "#34d399", "#f472b6"];
const MAX = 4;
const W = 960;
const H = 280;
const PAD_R = 64;
const AXIS = 20;

function CompareChart({ data }: { data: CompareResponse }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = data.window_candles;
  const plotW = W - PAD_R;
  const plotH = H - AXIS;
  const all = data.stocks.flatMap((s) => s.series);
  const lo = Math.min(100, ...all);
  const hi = Math.max(100, ...all);
  const pad = (hi - lo) * 0.08 || 1;
  const top = hi + pad;
  const span = top - (lo - pad) || 1;
  const y = (v: number) => ((top - v) / span) * plotH;
  const x = (i: number) => (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const times = data.stocks[0]?.times ?? [];
  const at = hover ?? n - 1;

  return (
    <div className="space-y-2">
      <p data-testid="compare-readout" className="font-mono text-[11px] tabular-nums text-slate-400">
        <span className="text-slate-500">{times[at] ? stamp(times[at], data.interval) : ""}</span>
        {data.stocks.map((s, k) => <span key={s.symbol} style={{ color: COLORS[k] }}> {s.symbol} {s.series[at] ?? "—"}</span>)}
      </p>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        data-testid="compare-chart"
        role="img"
        aria-label={`Price lines rebased to 100, ${intervalName(data.interval)} candles`}
        className="h-auto w-full touch-pan-y select-none rounded-lg bg-[#090d15]"
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - rect.left) / rect.width) * W;
          setHover(n <= 1 ? 0 : Math.max(0, Math.min(n - 1, Math.round((px / plotW) * (n - 1)))));
        }}
        onPointerLeave={() => setHover(null)}
      >
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const v = top - span * f;
          return (
            <g key={f}>
              <line x1={0} x2={plotW} y1={f * plotH} y2={f * plotH} stroke="#1a2336" />
              <text x={plotW + 6} y={Math.max(10, f * plotH + 3)} fontSize={10} fill="#64748b" fontFamily="monospace">{v.toFixed(1)}</text>
            </g>
          );
        })}
        <line x1={0} x2={plotW} y1={y(100)} y2={y(100)} stroke="#64748b" strokeDasharray="5 4" />
        {data.stocks.map((s, k) => (
          <polyline key={s.symbol} data-testid={`compare-line-${s.symbol}`} fill="none" stroke={COLORS[k]} strokeWidth={1.6} points={s.series.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
        ))}
        {times.length > 0 && [0, Math.floor((n - 1) / 2), n - 1].map((i, k) => (
          <text key={`${i}-${k}`} x={Math.min(plotW - 60, Math.max(0, x(i) - 24))} y={H - 5} fontSize={10} fill="#64748b" fontFamily="monospace">{stamp(times[i], data.interval)}</text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={plotH} stroke="#94a3b8" strokeOpacity={0.5} strokeDasharray="3 3" pointerEvents="none" />}
      </svg>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
        {data.stocks.map((s, k) => <span key={s.symbol}><span style={{ color: COLORS[k] }}>━</span> {s.symbol}</span>)}
        <span>Every line starts at 100, so a reading of 104 means +4% since the start of the window ({n} candles).</span>
      </p>
    </div>
  );
}

// Side by side comparison of 2 to 4 stocks: price lines rebased to 100, the engine's reading and the key numbers.
export default function StockCompare() {
  const [params, setParams] = useSearchParams();
  const meta = useStocksMeta();
  const symbols = useMemo(() => Array.from(new Set((params.get("symbols") ?? "").split(",").map((s) => s.trim().toUpperCase()).filter(Boolean))).slice(0, MAX), [params]);
  const requested = Number(params.get("interval"));
  const interval = (INTERVAL_OPTIONS.some((o) => o.value === requested) ? requested : 1440) as Interval;
  const names = new Map((meta.data?.stocks ?? []).map((s) => [s.symbol, s.name]));
  const [adding, setAdding] = useState("");

  const update = (next: string[], nextInterval: number = interval) => {
    const copy = new URLSearchParams();
    if (next.length) copy.set("symbols", next.join(","));
    copy.set("interval", String(nextInterval));
    setParams(copy, { replace: true });
  };

  const compare = useQuery({
    queryKey: ["premium-compare", symbols.join(","), interval],
    queryFn: () => apiGet<CompareResponse>(`/premium/stocks/compare?symbols=${encodeURIComponent(symbols.join(","))}&interval=${interval}`),
    enabled: symbols.length >= 2,
    refetchInterval: 10_000,
    retry: false,
    placeholderData: keepPreviousData,
  });
  const data = compare.data;
  const choices = (meta.data?.stocks ?? []).filter((s) => !symbols.includes(s.symbol));

  return (
    <div data-testid="stock-compare-page" className="space-y-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-xs">
        <Link to="/premium/stocks" className="rounded-md border border-[#26334b] px-3 py-1.5 text-slate-300 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">← All stocks</Link>
        <h1 className="font-heading text-base text-slate-100">Compare stocks</h1>
      </nav>

      <section className="space-y-3 rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-2">
          {symbols.map((s, k) => (
            <span key={s} data-testid={`compare-chip-${s}`} className="inline-flex items-center gap-1.5 rounded-full border border-[#2a364f] bg-[#0e131d] py-1 pl-3 pr-1.5 text-xs text-slate-200">
              <span style={{ color: COLORS[k] }}>●</span>
              <span className="font-semibold">{s}</span>
              {names.get(s) && <span className="hidden max-w-[10rem] truncate text-[10px] text-slate-500 sm:inline">{names.get(s)}</span>}
              <button type="button" aria-label={`Remove ${s}`} onClick={() => update(symbols.filter((x) => x !== s))} className="size-5 rounded-full text-slate-500 hover:bg-[#1a2336] hover:text-rose-300">×</button>
            </span>
          ))}
          {symbols.length < MAX && (
            <select data-testid="compare-add" value={adding} aria-label="Add a stock to compare" onChange={(event) => { const v = event.target.value; setAdding(""); if (v) update([...symbols, v]); }} className="h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300">
              <option value="">+ Add a stock</option>
              {choices.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol} · {s.name}</option>)}
            </select>
          )}
          <select data-testid="compare-interval" value={interval} aria-label="Timeframe" onChange={(event) => update(symbols, Number(event.target.value))} className="ml-auto h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300">
            {INTERVAL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label} candles</option>)}
          </select>
        </div>
        {meta.isError && <p className="text-[11px] text-slate-500">The stock list couldn't be loaded, so adding stocks is paused.</p>}

        {symbols.length < 2 && <p data-testid="compare-need-two" className="rounded-lg border border-dashed border-[#202b42] p-6 text-center text-xs text-slate-500">Pick {symbols.length === 0 ? "two to four" : "at least one more"} stock{symbols.length === 0 ? "s" : ""} to compare.</p>}
        {symbols.length >= 2 && compare.isError && <p role="alert" className="rounded-lg border border-[#202b42] p-4 text-xs text-slate-400">The comparison is unavailable right now. Check the stocks and timeframe, then try again.</p>}
        {symbols.length >= 2 && compare.isPending && <p className="p-4 text-xs text-slate-500">Loading comparison…</p>}
        {data && data.window_candles === 0 && <p data-testid="compare-no-candles" className="rounded-lg border border-dashed border-[#202b42] p-6 text-center text-xs text-slate-500">There are no candles for this timeframe yet, so there is nothing to draw. Try a longer timeframe, or wait for live ticks.</p>}
        {data && data.window_candles > 0 && <CompareChart data={data} />}
      </section>

      {data && (
        <section className="overflow-x-auto rounded-xl border border-[#202b42] bg-[#0c0f17]/95">
          <table data-testid="compare-table" className="w-full min-w-[720px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-3 py-2">Stock</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Today</th>
                <th className="px-3 py-2 text-right">Over window</th>
                <th className="px-3 py-2">Signal</th>
                <th className="px-3 py-2">Trend</th>
                <th className="px-3 py-2 text-right">RSI</th>
                <th className="px-3 py-2">Volatility</th>
                <th className="px-3 py-2 text-right">Rel. vol</th>
              </tr>
            </thead>
            <tbody>
              {data.stocks.map((s, k) => (
                <tr key={s.symbol} data-testid={`compare-row-${s.symbol}`} className="border-t border-[#161e30]">
                  <td className="px-3 py-2">
                    <Link to={`/premium/stocks/${encodeURIComponent(s.symbol)}`} className="font-semibold text-slate-100 hover:underline"><span style={{ color: COLORS[k] }}>● </span>{s.symbol}</Link>
                    <span className="block max-w-[14rem] truncate text-[10px] text-slate-500">{s.name} · {s.sector}</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-white">{price(s.quote?.ltp)}</td>
                  <td className={`px-3 py-2 text-right font-mono tabular-nums ${tone(s.quote?.change_pct)}`}>{signed(s.quote?.change_pct, "%")}</td>
                  <td className={`px-3 py-2 text-right font-mono tabular-nums ${tone(s.change_over_window_pct)}`}>{signed(s.change_over_window_pct, "%")}</td>
                  <td className="px-3 py-2"><div className="flex flex-wrap items-center gap-1.5"><BiasPill bias={s.bias} /><DataBadge data={{ status: s.data_status, tick_age_seconds: s.market.tick_age_seconds, message: s.market.message }} /></div></td>
                  <td className="px-3 py-2 text-slate-400">{s.trend.toLowerCase()}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-300">{s.rsi ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-400">{s.volatility?.label ?? "—"}{s.volatility?.atr_pct != null ? ` · ${s.volatility.atr_pct}%` : ""}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-300">{s.relative_volume != null ? `${s.relative_volume}x` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#202b42] px-3 py-2">
            <p className="text-[10px] leading-relaxed text-slate-600">{data.note} Volume today: {data.stocks.map((s) => `${s.symbol} ${whole(s.quote?.volume)}`).join(" · ")}.</p>
            {data.stocks[0] && <MarketBadge market={data.stocks[0].market} />}
          </div>
        </section>
      )}
    </div>
  );
}
