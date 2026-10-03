import { useEffect, useState } from "react";

import type { ChartOptions } from "@/components/premium/PriceChart";
import { ApiError } from "@/lib/api";
import { DEFAULT_EMA, INTERVAL_OPTIONS, checkName, validEma, type Interval, type Layout } from "@/lib/premium";
import { useLayouts } from "@/lib/premiumData";

export function Toggle({ on, label, onClick, testId }: { on: boolean; label: string; onClick: () => void; testId: string }) {
  return (
    <button type="button" data-testid={testId} aria-pressed={on} onClick={onClick} className={`h-7 rounded-md border px-2.5 text-[11px] transition-colors ${on ? "border-blue-400/50 bg-blue-500/15 text-blue-200" : "border-[#26334b] text-slate-400 hover:bg-[#1a2336]"}`}>
      {label}
    </button>
  );
}

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (error.status === 403) return "Premium access is needed to save layouts.";
  }
  return "That didn't go through. Try again shortly.";
}

function LayoutMenu({ current, apply }: { current: Layout; apply: (layout: Layout) => void }) {
  const store = useLayouts();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null);
  const names = Object.keys(store.layouts).sort((a, b) => a.localeCompare(b));

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const save = async () => {
    const trimmed = name.trim();
    const bad = checkName(trimmed);
    if (bad) {
      setMessage({ text: bad, bad: true });
      return;
    }
    try {
      await store.save(trimmed, current);
      setName("");
      setMessage({ text: `Saved “${trimmed}”.`, bad: false });
    } catch (error) {
      setMessage({ text: explain(error), bad: true });
    }
  };

  return (
    <div className="relative">
      <button type="button" data-testid="layouts-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)} className={`h-7 rounded-md border px-2.5 text-[11px] ${open ? "border-amber-300/50 bg-amber-300/10 text-amber-200" : "border-[#26334b] text-slate-300 hover:bg-[#1a2336]"}`}>Layouts{names.length ? ` (${names.length})` : ""} ▾</button>
      {open && (
        <div data-testid="layouts-panel" role="group" aria-label="Saved chart layouts" className="absolute right-0 z-20 mt-1 w-72 max-w-[85vw] rounded-lg border border-[#2a364f] bg-[#0e131d] p-3 shadow-xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Saved layouts</p>
          {store.failed && <p className="mt-2 text-[11px] text-rose-300">Layouts couldn't be loaded right now.</p>}
          {!store.failed && names.length === 0 && <p className="mt-2 text-[11px] text-slate-500">{store.loading ? "Loading…" : "None yet. Set up the chart, then save it below."}</p>}
          <ul className="mt-2 space-y-1">
            {names.map((layoutName) => {
              const layout = store.layouts[layoutName];
              return (
                <li key={layoutName} className="flex items-center gap-1">
                  <button type="button" data-testid={`layout-apply-${layoutName}`} onClick={() => { apply(layout); setOpen(false); }} className="min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-left text-xs text-slate-200 hover:bg-[#1a2336]" title={`Timeframe ${layout.interval}m · EMA ${layout.ema_fast}/${layout.ema_slow}`}>{layoutName}<span className="ml-2 text-[10px] text-slate-500">EMA {layout.ema_fast}/{layout.ema_slow}</span></button>
                  <button type="button" aria-label={`Delete layout ${layoutName}`} data-testid={`layout-delete-${layoutName}`} disabled={store.busy} onClick={() => void store.remove(layoutName).catch((error) => setMessage({ text: explain(error), bad: true }))} className="h-7 w-7 shrink-0 rounded-md text-slate-500 hover:bg-[#1a2336] hover:text-rose-300 disabled:opacity-50">×</button>
                </li>
              );
            })}
          </ul>
          <form className="mt-3 flex gap-2 border-t border-[#202b42] pt-3" onSubmit={(event) => { event.preventDefault(); void save(); }}>
            <input data-testid="layout-name" value={name} maxLength={30} onChange={(event) => setName(event.target.value)} placeholder="Name this layout" aria-label="Layout name" className="h-8 min-w-0 flex-1 rounded-md border border-[#2a364f] bg-[#0b0f17] px-2 text-xs text-slate-200 placeholder:text-slate-600" />
            <button type="submit" data-testid="layout-save" disabled={store.busy} className="h-8 rounded-md bg-amber-300 px-3 text-xs font-semibold text-[#1a1203] hover:bg-amber-200 disabled:opacity-60">Save</button>
          </form>
          <p className="mt-2 text-[10px] leading-snug text-slate-600">Saves the timeframe, EMA periods, indicators and lower pane. Layouts belong to your account.</p>
          {message && <p role={message.bad ? "alert" : "status"} className={`mt-1 text-[11px] ${message.bad ? "text-rose-300" : "text-emerald-300"}`}>{message.text}</p>}
        </div>
      )}
    </div>
  );
}

interface Props {
  interval: Interval;
  onInterval: (value: Interval) => void;
  options: ChartOptions;
  onOptions: (options: ChartOptions) => void;
  hasVolume: boolean;
  hasEngine: boolean;
  ema?: [number, number]; // with onEma: custom EMA periods and saved layouts are offered
  onEma?: (value: [number, number]) => void;
}

// Timeframes, indicator toggles, customizable EMA periods and saved layouts for a chart.
export default function ChartToolbar({ interval, onInterval, options, onOptions, hasVolume, hasEngine, ema, onEma }: Props) {
  const periods = ema ?? DEFAULT_EMA;
  const [fastPeriod, slowPeriod] = periods;
  const [draft, setDraft] = useState<{ fast: string; slow: string }>({ fast: String(fastPeriod), slow: String(slowPeriod) });
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    setDraft({ fast: String(fastPeriod), slow: String(slowPeriod) });
    setProblem(null);
  }, [fastPeriod, slowPeriod]);

  const flip = (key: "ema" | "bb" | "vwap" | "levels" | "patterns" | "setup") => onOptions({ ...options, [key]: !options[key] });
  const changed = periods[0] !== DEFAULT_EMA[0] || periods[1] !== DEFAULT_EMA[1];

  const commit = () => {
    if (!onEma) return;
    const fast = Number(draft.fast);
    const slow = Number(draft.slow);
    const bad = validEma(fast, slow);
    setProblem(bad);
    if (!bad && (fast !== periods[0] || slow !== periods[1])) onEma([fast, slow]);
  };

  const current: Layout = { ema_fast: periods[0], ema_slow: periods[1], interval, pane: options.pane, ema: options.ema, bb: options.bb, vwap: options.vwap, levels: options.levels, patterns: options.patterns, setup: options.setup };
  const apply = (layout: Layout) => {
    onInterval(layout.interval);
    onEma?.([layout.ema_fast, layout.ema_slow]);
    onOptions({ ...options, ema: layout.ema, bb: layout.bb, vwap: layout.vwap, levels: layout.levels, patterns: layout.patterns, setup: layout.setup, pane: layout.pane });
  };

  return (
    <div className="mb-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex max-w-full items-center gap-1 overflow-x-auto" role="group" aria-label="Candle size">
          {INTERVAL_OPTIONS.map((option) => (
            <button key={option.value} type="button" data-testid={`interval-${option.value}`} aria-pressed={interval === option.value} onClick={() => onInterval(option.value)} className={`h-7 shrink-0 rounded-md px-2.5 text-[11px] font-semibold ${interval === option.value ? "bg-[#1f2a41] text-white" : "text-slate-400 hover:text-slate-200"}`}>{option.label}</button>
          ))}
        </div>
        {onEma && (
          <div className="ml-auto sm:ml-2"><LayoutMenu current={current} apply={apply} /></div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Toggle on={options.ema} label={`EMA ${periods[0]}/${periods[1]}`} testId="toggle-ema" onClick={() => flip("ema")} />
        {onEma && (
          <form className="flex items-center gap-1 text-[11px] text-slate-400" onSubmit={(event) => { event.preventDefault(); commit(); }}>
            <label className="sr-only" htmlFor="ema-fast">Fast EMA period</label>
            <input id="ema-fast" data-testid="ema-fast" inputMode="numeric" value={draft.fast} onChange={(event) => setDraft((d) => ({ ...d, fast: event.target.value }))} onBlur={commit} className="h-7 w-12 rounded-md border border-[#2a364f] bg-[#0e131d] px-1.5 text-center font-mono text-xs text-slate-200" />
            <span aria-hidden>/</span>
            <label className="sr-only" htmlFor="ema-slow">Slow EMA period</label>
            <input id="ema-slow" data-testid="ema-slow" inputMode="numeric" value={draft.slow} onChange={(event) => setDraft((d) => ({ ...d, slow: event.target.value }))} onBlur={commit} className="h-7 w-12 rounded-md border border-[#2a364f] bg-[#0e131d] px-1.5 text-center font-mono text-xs text-slate-200" />
            {changed && <button type="button" data-testid="ema-reset" onClick={() => onEma([DEFAULT_EMA[0], DEFAULT_EMA[1]])} className="h-7 rounded-md px-2 text-[11px] text-sky-300 hover:bg-[#1a2336]">Reset 9/20</button>}
          </form>
        )}
        <span className="hidden h-4 w-px bg-[#202b42] sm:block" />
        <Toggle on={options.bb} label="Bollinger" testId="toggle-bb" onClick={() => flip("bb")} />
        {hasVolume && <Toggle on={options.vwap} label="VWAP" testId="toggle-vwap" onClick={() => flip("vwap")} />}
        <Toggle on={options.levels} label="Support / resistance" testId="toggle-levels" onClick={() => flip("levels")} />
        {hasEngine && <Toggle on={options.patterns} label="Patterns" testId="toggle-patterns" onClick={() => flip("patterns")} />}
        {hasEngine && <Toggle on={options.setup} label="Buy/sell zone" testId="toggle-setup" onClick={() => flip("setup")} />}
        <span className="hidden h-4 w-px bg-[#202b42] sm:block" />
        {(["rsi", "macd", "none"] as const).map((pane) => (
          <Toggle key={pane} on={options.pane === pane} label={pane === "none" ? "No pane" : pane.toUpperCase()} testId={`pane-${pane}`} onClick={() => onOptions({ ...options, pane })} />
        ))}
      </div>
      {problem && <p data-testid="ema-error" role="alert" className="text-[11px] text-rose-300">{problem}</p>}
    </div>
  );
}
