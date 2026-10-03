import { useState, type ReactNode } from "react";

import { LevelsCard, QuoteHeader, SignalCard, TrendCard, VolumeCard } from "@/components/premium/AnalysisPanels";
import ChartToolbar from "@/components/premium/ChartToolbar";
import PriceChart, { type ChartOptions } from "@/components/premium/PriceChart";
import { EngineCard, PatternsCard, SetupCard } from "@/components/premium/StockPanels";
import { sessionLabel, type Detail, type Interval } from "@/lib/premium";

interface Props {
  detail: Detail;
  interval: Interval;
  onInterval: (value: Interval) => void;
  ema?: [number, number]; // with onEma: customizable EMA periods and saved layouts
  onEma?: (value: [number, number]) => void;
  hideHeader?: boolean; // the stock page draws its own header
  performance?: ReactNode; // tested-history card, placed right after the trade setup
  children?: ReactNode; // extra cards, placed at the end of the card grid
}

// One instrument: quote, interactive chart with indicators, the signal engine, trend, levels and volume.
export default function AnalysisView({ detail, interval, onInterval, ema, onEma, hideHeader = false, performance, children }: Props) {
  const [options, setOptions] = useState<ChartOptions>({ ema: true, bb: false, vwap: true, levels: true, patterns: true, setup: true, pane: "rsi" });
  const analysis = detail.analysis;
  const engine = detail.engine ?? null;
  const hasVolume = analysis.volume.available;
  return (
    <div data-testid="analysis-view" className="space-y-3">
      {!hideHeader && <QuoteHeader name={detail.name} quote={detail.quote} market={detail.market} />}
      <div className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3">
        <ChartToolbar interval={interval} onInterval={onInterval} options={options} onOptions={setOptions} hasVolume={hasVolume} hasEngine={engine !== null} ema={ema} onEma={onEma} />
        {analysis.session_day && (
          <p data-testid="session-banner" className="mb-3 rounded-md border border-zinc-600/50 bg-zinc-900/60 px-3 py-2 text-[11px] leading-relaxed text-zinc-300">The market is closed and nothing has traded today, so this chart shows the last recorded session, <span className="font-semibold text-white">{sessionLabel(analysis.session_day)}</span>. Candle times are from that day.</p>
        )}
        {interval >= 30 && analysis.history_available === false && (
          <p data-testid="history-missing" className="mb-3 rounded-md border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] leading-relaxed text-amber-200">Longer timeframes need stored history, and none is saved for {detail.name} yet. The owner can load it with the history import tool (tools/import_upstox_index_history.py, add --stocks for stocks). Until then this chart only has what was recorded today.</p>
        )}
        <PriceChart analysis={analysis} options={{ ...options, vwap: options.vwap && hasVolume }} engine={engine} />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {engine ? <EngineCard engine={engine} analysis={analysis} /> : <SignalCard analysis={analysis} />}
        {engine && <SetupCard engine={engine} last={detail.quote?.ltp ?? null} />}
        {performance}
        <TrendCard analysis={analysis} />
        <LevelsCard analysis={analysis} last={detail.quote?.ltp ?? null} />
        <VolumeCard analysis={analysis} />
        {engine && <PatternsCard engine={engine} interval={analysis.interval} />}
        {children}
      </div>
    </div>
  );
}
