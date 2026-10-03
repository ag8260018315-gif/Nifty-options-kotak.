import { useState } from "react";

import { LevelsCard, QuoteHeader, SignalCard, TrendCard, VolumeCard } from "@/components/premium/AnalysisPanels";
import PriceChart, { type ChartOptions } from "@/components/premium/PriceChart";
import { INTERVAL_OPTIONS, type Detail, type Interval } from "@/lib/premium";

function Toggle({ on, label, onClick, testId }: { on: boolean; label: string; onClick: () => void; testId: string }) {
  return (
    <button type="button" data-testid={testId} aria-pressed={on} onClick={onClick} className={`h-7 rounded-md border px-2.5 text-[11px] transition-colors ${on ? "border-blue-400/50 bg-blue-500/15 text-blue-200" : "border-[#26334b] text-slate-400 hover:bg-[#1a2336]"}`}>
      {label}
    </button>
  );
}

// One instrument: quote, interactive chart with indicators, signal, trend, levels and volume.
export default function AnalysisView({ detail, interval, onInterval }: { detail: Detail; interval: Interval; onInterval: (value: Interval) => void }) {
  const [options, setOptions] = useState<ChartOptions>({ ema: true, bb: false, vwap: true, levels: true, pane: "rsi" });
  const analysis = detail.analysis;
  const flip = (key: "ema" | "bb" | "vwap" | "levels") => setOptions((o) => ({ ...o, [key]: !o[key] }));
  const hasVolume = analysis.volume.available;
  return (
    <div data-testid="analysis-view" className="space-y-3">
      <QuoteHeader name={detail.name} quote={detail.quote} market={detail.market} />
      <div className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1" role="group" aria-label="Candle size">
            {INTERVAL_OPTIONS.map((option) => (
              <button key={option.value} type="button" data-testid={`interval-${option.value}`} aria-pressed={interval === option.value} onClick={() => onInterval(option.value)} className={`h-7 rounded-md px-2.5 text-[11px] font-semibold ${interval === option.value ? "bg-[#1f2a41] text-white" : "text-slate-400 hover:text-slate-200"}`}>{option.label}</button>
            ))}
          </div>
          <span className="hidden h-4 w-px bg-[#202b42] sm:block" />
          <Toggle on={options.ema} label="EMA 9/21" testId="toggle-ema" onClick={() => flip("ema")} />
          <Toggle on={options.bb} label="Bollinger" testId="toggle-bb" onClick={() => flip("bb")} />
          {hasVolume && <Toggle on={options.vwap} label="VWAP" testId="toggle-vwap" onClick={() => flip("vwap")} />}
          <Toggle on={options.levels} label="Support / resistance" testId="toggle-levels" onClick={() => flip("levels")} />
          <span className="hidden h-4 w-px bg-[#202b42] sm:block" />
          {(["rsi", "macd", "none"] as const).map((pane) => (
            <Toggle key={pane} on={options.pane === pane} label={pane === "none" ? "No pane" : pane.toUpperCase()} testId={`pane-${pane}`} onClick={() => setOptions((o) => ({ ...o, pane }))} />
          ))}
        </div>
        {interval >= 60 && analysis.history_available === false && (
          <p data-testid="history-missing" className="mb-3 rounded-md border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] leading-relaxed text-amber-200">Long timeframes need stored history, and none is saved for {detail.name} yet. The owner can load it with the history import tool (tools/import_upstox_index_history.py). Until then this chart only has what was recorded today.</p>
        )}
        <PriceChart analysis={analysis} options={{ ...options, vwap: options.vwap && hasVolume }} />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <SignalCard analysis={analysis} />
        <TrendCard analysis={analysis} />
        <LevelsCard analysis={analysis} last={detail.quote?.ltp ?? null} />
        <VolumeCard analysis={analysis} />
      </div>
    </div>
  );
}
