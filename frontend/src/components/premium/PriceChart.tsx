import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { intervalName, price, stamp, whole, type Analysis } from "@/lib/premium";

// Interactive SVG candlestick chart: hover for values, drag to pan, wheel or +/- to zoom.
// Overlays: fast/slow EMA (default 9/20), Bollinger bands, VWAP, support/resistance and pivots. Panes: volume, RSI or MACD.

export interface ChartOptions {
  ema: boolean;
  bb: boolean;
  vwap: boolean;
  levels: boolean;
  pane: "rsi" | "macd" | "none";
}

const W = 960;
const PAD_R = 64;
const H_PRICE = 300;
const H_VOL = 64;
const H_IND = 92;
const GAP = 10;
const AXIS = 20;
const MIN_BARS = 20;

type Nums = (number | null)[];

function pathFor(values: Nums | undefined, start: number, end: number, x: (i: number) => number, y: (v: number) => number): string {
  if (!values) return "";
  let d = "";
  let pen = false;
  for (let i = start; i < end; i++) {
    const v = values[i];
    if (v === null || v === undefined) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  }
  return d;
}

export default function PriceChart({ analysis, options }: { analysis: Analysis; options: ChartOptions }) {
  const candles = analysis.candles;
  const series = analysis.series;
  const n = candles.length;
  const [count, setCount] = useState(90);
  const [offset, setOffset] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ x: number; offset: number } | null>(null);

  const visibleCount = Math.max(1, Math.min(count, n));
  const off = Math.min(offset, Math.max(0, n - visibleCount));
  const end = n - off;
  const start = Math.max(0, end - visibleCount);
  const plotW = W - PAD_R;
  const slot = plotW / visibleCount;
  const bodyW = Math.max(1, Math.min(14, slot * 0.64));
  const x = (i: number) => (i - start + 0.5) * slot;
  const hasVolume = analysis.volume.available;
  const showPane = options.pane !== "none" && !!series;
  const height = H_PRICE + (hasVolume ? GAP + H_VOL : 0) + (showPane ? GAP + H_IND : 0) + AXIS;

  const zoom = (factor: number) => setCount((c) => Math.round(Math.max(MIN_BARS, Math.min(Math.max(n, MIN_BARS), c * factor))));

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      setCount((c) => Math.round(Math.max(MIN_BARS, Math.min(Math.max(n, MIN_BARS), c * (event.deltaY < 0 ? 0.85 : 1.18)))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [n]);

  const domain = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = start; i < end; i++) {
      lo = Math.min(lo, candles[i].low);
      hi = Math.max(hi, candles[i].high);
      if (options.bb && series) {
        const u = series.bb_upper[i];
        const l = series.bb_lower[i];
        if (u !== null && u !== undefined) hi = Math.max(hi, u);
        if (l !== null && l !== undefined) lo = Math.min(lo, l);
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { lo: 0, hi: 1 };
    const pad = (hi - lo) * 0.06 || hi * 0.001 || 1;
    return { lo: lo - pad, hi: hi + pad };
  }, [candles, series, start, end, options.bb]);

  if (n === 0) {
    return <div data-testid="chart-empty" className="flex h-64 items-center justify-center rounded-lg border border-dashed border-[#202b42] px-4 text-center text-xs text-slate-500">No live candles yet. They appear once live ticks arrive during market hours (09:15–15:30 IST).</div>;
  }

  const span = domain.hi - domain.lo || 1;
  const yPrice = (v: number) => ((domain.hi - v) / span) * H_PRICE;
  const volTop = H_PRICE + GAP;
  let maxVol = 0;
  for (let i = start; i < end; i++) maxVol = Math.max(maxVol, candles[i].volume);
  const indTop = H_PRICE + (hasVolume ? GAP + H_VOL : 0) + GAP;

  const inView = (v: number | null | undefined): v is number => v !== null && v !== undefined && v >= domain.lo && v <= domain.hi;
  const levelLines: { value: number; label: string; color: string }[] = [];
  if (options.levels && analysis.levels) {
    for (const v of analysis.levels.resistance) if (inView(v)) levelLines.push({ value: v, label: "R", color: "#fb7185" });
    for (const v of analysis.levels.support) if (inView(v)) levelLines.push({ value: v, label: "S", color: "#34d399" });
    const pp = analysis.levels.pivots?.pp;
    if (inView(pp)) levelLines.push({ value: pp, label: "PP", color: "#38bdf8" });
  }

  const pointerIndex = (clientX: number): number | null => {
    const el = svgRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * W;
    const idx = start + Math.floor(px / slot);
    return idx >= start && idx < end ? idx : null;
  };

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    drag.current = { x: event.clientX, offset: off };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const el = svgRef.current;
    if (drag.current && el) {
      const rect = el.getBoundingClientRect();
      const moved = Math.round((((event.clientX - drag.current.x) / rect.width) * W) / slot);
      setOffset(Math.max(0, Math.min(Math.max(0, n - visibleCount), drag.current.offset + moved)));
    }
    setHover(pointerIndex(event.clientX));
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  const shown = hover ?? end - 1;
  const bar = candles[Math.max(0, Math.min(n - 1, shown))];
  const at = (values: Nums | undefined) => (values ? values[Math.max(0, Math.min(n - 1, shown))] : null);
  const last = candles[n - 1];
  const labelStep = Math.max(1, Math.round(visibleCount / (analysis.interval >= 60 ? 4 : 6)));
  const volLabel = (v: number) => (v >= 1e7 ? `${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : String(v));

  return (
    <div data-testid="price-chart" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p data-testid="chart-readout" className="font-mono text-[11px] tabular-nums text-slate-400">
          <span className="text-slate-500">{stamp(bar.time, analysis.interval)}</span> O {price(bar.open)} H {price(bar.high)} L {price(bar.low)} <span className={bar.close >= bar.open ? "text-emerald-300" : "text-rose-300"}>C {price(bar.close)}</span>
          {hasVolume && <> V {whole(bar.volume)}</>}
          {options.ema && <> <span className="text-amber-300">E{analysis.ema_periods?.[0] ?? 9} {price(at(series?.ema_fast))}</span> <span className="text-sky-300">E{analysis.ema_periods?.[1] ?? 20} {price(at(series?.ema_slow))}</span></>}
        </p>
        <div className="flex items-center gap-1" role="group" aria-label="Chart zoom">
          <button type="button" aria-label="Zoom out" onClick={() => zoom(1.3)} className="h-7 w-7 rounded-md border border-[#26334b] text-sm text-slate-300 hover:bg-[#1a2336]">−</button>
          <button type="button" aria-label="Zoom in" onClick={() => zoom(0.77)} className="h-7 w-7 rounded-md border border-[#26334b] text-sm text-slate-300 hover:bg-[#1a2336]">+</button>
          <button type="button" aria-label="Show latest" onClick={() => { setOffset(0); setCount(90); }} className="h-7 rounded-md border border-[#26334b] px-2 text-[11px] text-slate-300 hover:bg-[#1a2336]">Latest</button>
        </div>
      </div>
      <svg
        ref={svgRef}
        data-testid="chart-svg"
        viewBox={`0 0 ${W} ${height}`}
        className="h-auto w-full touch-pan-y select-none rounded-lg bg-[#090d15]"
        role="img"
        aria-label={`Candlestick chart, ${intervalName(analysis.interval)} candles`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => { drag.current = null; setHover(null); }}
      >
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const v = domain.hi - span * f;
          return (
            <g key={f}>
              <line x1={0} x2={plotW} y1={f * H_PRICE} y2={f * H_PRICE} stroke="#1a2336" strokeWidth={1} />
              <text x={plotW + 6} y={f * H_PRICE + 3} fontSize={10} fill="#64748b" fontFamily="monospace">{price(v)}</text>
            </g>
          );
        })}
        {levelLines.map((l) => (
          <g key={`${l.label}-${l.value}`}>
            <line x1={0} x2={plotW} y1={yPrice(l.value)} y2={yPrice(l.value)} stroke={l.color} strokeOpacity={0.55} strokeDasharray="5 4" strokeWidth={1} />
            <text x={plotW + 6} y={yPrice(l.value) + 3} fontSize={9} fill={l.color} fontFamily="monospace">{l.label} {price(l.value)}</text>
          </g>
        ))}
        {options.bb && series && (
          <>
            <path d={pathFor(series.bb_upper, start, end, x, yPrice)} fill="none" stroke="#a78bfa" strokeOpacity={0.6} strokeWidth={1} />
            <path d={pathFor(series.bb_lower, start, end, x, yPrice)} fill="none" stroke="#a78bfa" strokeOpacity={0.6} strokeWidth={1} />
          </>
        )}
        {candles.slice(start, end).map((c, k) => {
          const i = start + k;
          const up = c.close >= c.open;
          const color = up ? "#34d399" : "#fb7185";
          const top = yPrice(Math.max(c.open, c.close));
          const bottom = yPrice(Math.min(c.open, c.close));
          return (
            <g key={c.time}>
              <line x1={x(i)} x2={x(i)} y1={yPrice(c.high)} y2={yPrice(c.low)} stroke={color} strokeWidth={1} />
              <rect x={x(i) - bodyW / 2} y={top} width={bodyW} height={Math.max(1, bottom - top)} fill={color} />
            </g>
          );
        })}
        {options.ema && series && (
          <>
            <path d={pathFor(series.ema_fast, start, end, x, yPrice)} fill="none" stroke="#fbbf24" strokeWidth={1.4} />
            <path d={pathFor(series.ema_slow, start, end, x, yPrice)} fill="none" stroke="#38bdf8" strokeWidth={1.4} />
          </>
        )}
        {options.vwap && series && <path d={pathFor(series.vwap, start, end, x, yPrice)} fill="none" stroke="#f472b6" strokeWidth={1.4} strokeDasharray="2 3" />}
        <line x1={0} x2={plotW} y1={yPrice(last.close)} y2={yPrice(last.close)} stroke="#60a5fa" strokeWidth={1} strokeDasharray="4 4" />
        <rect x={plotW + 2} y={yPrice(last.close) - 8} width={PAD_R - 4} height={16} rx={3} fill="#1d4ed8" />
        <text x={plotW + 6} y={yPrice(last.close) + 4} fontSize={10} fill="#fff" fontFamily="monospace">{price(last.close)}</text>

        {hasVolume && (
          <g>
            <text x={4} y={volTop + 10} fontSize={9} fill="#64748b">Volume {volLabel(maxVol)}</text>
            {candles.slice(start, end).map((c, k) => {
              const h = maxVol ? (c.volume / maxVol) * (H_VOL - 12) : 0;
              return <rect key={c.time} x={x(start + k) - bodyW / 2} y={volTop + H_VOL - h} width={bodyW} height={Math.max(0, h)} fill={c.close >= c.open ? "#34d399" : "#fb7185"} fillOpacity={0.55} />;
            })}
          </g>
        )}

        {showPane && series && options.pane === "rsi" && (
          <g>
            <text x={4} y={indTop + 10} fontSize={9} fill="#64748b">RSI 14</text>
            {[30, 50, 70].map((lvl) => <line key={lvl} x1={0} x2={plotW} y1={indTop + H_IND - (lvl / 100) * H_IND} y2={indTop + H_IND - (lvl / 100) * H_IND} stroke="#1f2a41" strokeDasharray={lvl === 50 ? "2 4" : undefined} />)}
            <path d={pathFor(series.rsi, start, end, x, (v) => indTop + H_IND - (v / 100) * H_IND)} fill="none" stroke="#c084fc" strokeWidth={1.4} />
            <text x={plotW + 6} y={indTop + H_IND - 0.7 * H_IND + 3} fontSize={9} fill="#64748b" fontFamily="monospace">70</text>
            <text x={plotW + 6} y={indTop + H_IND - 0.3 * H_IND + 3} fontSize={9} fill="#64748b" fontFamily="monospace">30</text>
          </g>
        )}
        {showPane && series && options.pane === "macd" && (() => {
          let m = 0.0001;
          for (let i = start; i < end; i++) for (const v of [series.macd[i], series.macd_signal[i], series.macd_hist[i]]) if (v !== null && v !== undefined) m = Math.max(m, Math.abs(v));
          const yM = (v: number) => indTop + H_IND / 2 - (v / m) * (H_IND / 2 - 6);
          return (
            <g>
              <text x={4} y={indTop + 10} fontSize={9} fill="#64748b">MACD 12/26/9</text>
              <line x1={0} x2={plotW} y1={yM(0)} y2={yM(0)} stroke="#1f2a41" />
              {series.macd_hist.slice(start, end).map((v, k) => (v === null ? null : <rect key={start + k} x={x(start + k) - bodyW / 2} y={Math.min(yM(0), yM(v))} width={bodyW} height={Math.max(1, Math.abs(yM(v) - yM(0)))} fill={v >= 0 ? "#34d399" : "#fb7185"} fillOpacity={0.5} />))}
              <path d={pathFor(series.macd, start, end, x, yM)} fill="none" stroke="#38bdf8" strokeWidth={1.3} />
              <path d={pathFor(series.macd_signal, start, end, x, yM)} fill="none" stroke="#fbbf24" strokeWidth={1.3} />
            </g>
          );
        })()}

        {candles.slice(start, end).map((c, k) => (k % labelStep === 0 ? <text key={c.time} x={Math.min(plotW - (analysis.interval >= 60 ? 60 : 28), x(start + k) - 14)} y={height - 5} fontSize={10} fill="#64748b" fontFamily="monospace">{stamp(c.time, analysis.interval)}</text> : null))}
        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={0} y2={height - AXIS} stroke="#94a3b8" strokeOpacity={0.5} strokeDasharray="3 3" />
          </g>
        )}
      </svg>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
        {options.ema && <span><span className="text-amber-300">━</span> EMA {analysis.ema_periods?.[0] ?? 9} <span className="text-sky-300">━</span> EMA {analysis.ema_periods?.[1] ?? 20}</span>}
        {options.bb && <span><span className="text-violet-300">━</span> Bollinger 20,2</span>}
        {options.vwap && <span><span className="text-pink-300">┅</span> VWAP</span>}
        {options.levels && <span><span className="text-emerald-300">┅</span> support <span className="text-rose-300">┅</span> resistance <span className="text-sky-300">┅</span> pivot</span>}
        <span>Showing {end - start} of {n} candles. Drag to pan, scroll or +/− to zoom.</span>
      </p>
    </div>
  );
}
