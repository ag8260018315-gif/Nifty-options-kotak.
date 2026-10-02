import type { Detection, Marker, MarkerStatus } from "@/lib/orderblocks";

// A live list of the candle pattern markers drawn on the chart. These mark a pattern on past candles.
// They are not order data, they say nothing about what institutions did, and they are not advice.

const STATUS_TEXT: Record<MarkerStatus, string> = {
  "not-revisited": "Not revisited",
  revisited: "Price has traded back into it",
  "closed-through": "Price closed through it",
};

const STATUS_CLASS: Record<MarkerStatus, string> = {
  "not-revisited": "border-violet-400/30 bg-violet-400/10 text-violet-200",
  revisited: "border-blue-400/30 bg-blue-400/10 text-blue-200",
  "closed-through": "border-slate-500/30 bg-slate-500/10 text-slate-400",
};

const price = (value: number) => value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const points = (value: number) => value.toLocaleString("en-IN", { maximumFractionDigits: 1 });

function clock(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

function MarkerRow({ marker }: { marker: Marker }) {
  const closed = marker.status === "closed-through";
  const where = marker.side === "inside" ? "The last price is inside this range." : `The last price is ${points(marker.distancePoints)} points ${marker.side} this range.`;
  return (
    <li data-testid={`order-marker-row-${marker.id}`} className={`rounded-lg border border-[#202b42] bg-[#090d15] p-3 ${closed ? "opacity-70" : ""}`}>
      <div className="flex items-start gap-2.5">
        <span aria-hidden="true" className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-violet-400/50 bg-violet-400/10 text-[10px] font-semibold text-violet-200">{marker.id}</span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-slate-100">{marker.kind === "up-move" ? "Down candle before an up-move" : "Up candle before a down-move"}</p>
          <p className="mt-0.5 text-[11px] text-slate-500">{clock(marker.time)} IST · {marker.candlesAgo === 0 ? "latest candle" : `${marker.candlesAgo} ${marker.candlesAgo === 1 ? "candle" : "candles"} ago`}</p>
          <p className="mt-1.5 font-mono text-xs tabular-nums text-slate-200">{price(marker.low)} to {price(marker.high)}</p>
          <p className="mt-1 text-[11px] text-slate-500">The move after it was {marker.moveAtr.toFixed(1)} times the average candle range ({points(marker.movePoints)} points).</p>
          <span className={`mt-2 inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${STATUS_CLASS[marker.status]}`}>{STATUS_TEXT[marker.status]}</span>
          <p className="mt-1.5 text-[11px] text-slate-400">{where}</p>
        </div>
      </div>
    </li>
  );
}

export default function OrderBlockPanel({ symbol, intervalLabel, detection, hasCandles, lastPrice, enabled, onToggle }: { symbol: string; intervalLabel: string; detection: Detection; hasCandles: boolean; lastPrice: number | null; enabled: boolean; onToggle: (enabled: boolean) => void }) {
  return (
    <aside data-testid="order-marker-panel" aria-label="Candle pattern markers" className="flex min-w-0 flex-col rounded-xl border border-[#202b42] bg-[#0c111b] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-heading text-sm font-semibold text-slate-100">Candle pattern markers</h3>
          <p className="mt-0.5 text-[11px] text-slate-500">{symbol} · {intervalLabel} candles{lastPrice !== null ? ` · last ${price(lastPrice)}` : ""}</p>
        </div>
        <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-400">
          <input type="checkbox" data-testid="order-marker-toggle" checked={enabled} onChange={(event) => onToggle(event.target.checked)} className="size-3.5 accent-violet-500" />
          Show on chart
        </label>
      </div>

      <div className="mt-3 min-h-24">
        {!hasCandles ? (
          <p data-testid="order-marker-waiting" className="text-xs leading-relaxed text-slate-500">Waiting for candles. Markers appear once enough live candles have formed.</p>
        ) : !detection.ready ? (
          <p data-testid="order-marker-notready" className="text-xs leading-relaxed text-slate-500">{detection.reason}</p>
        ) : detection.markers.length === 0 ? (
          <p data-testid="order-marker-none" className="text-xs leading-relaxed text-slate-500">No markers in these candles right now. A marker needs a move of at least 1.5 times the average candle range, within 3 candles.</p>
        ) : (
          <ul data-testid="order-marker-list" className="space-y-2">
            {detection.markers.map((marker) => <MarkerRow key={`${marker.index}-${marker.kind}`} marker={marker} />)}
          </ul>
        )}
      </div>

      <details className="mt-3 text-[11px] leading-relaxed text-slate-500">
        <summary className="cursor-pointer text-slate-400 hover:text-slate-200">How these are found</summary>
        <p className="mt-2">A marker is the last candle that moved against a move that followed it: a down candle followed, within 3 candles, by an up-move of at least 1.5 times the average candle range (14 candles), or the reverse. The marked range is that candle's low to high. Each marker is then tracked live: not revisited, price traded back into it, or price closed through it.</p>
      </details>

      <p data-testid="order-marker-disclaimer" className="mt-3 border-t border-[#202b42] pt-3 text-[10px] leading-relaxed text-slate-600">
        This marks a chart pattern on past candles. It is not real order data, it does not show what institutions did, and it is not a recommendation to buy or sell. Markers can be wrong, and price may never come back to them.
      </p>
    </aside>
  );
}
