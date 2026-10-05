import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { MarketBadge } from "@/components/premium/AnalysisPanels";
import { apiGet } from "@/lib/api";
import { clockTime, signed, tone, type MarketSummary } from "@/lib/premium";

function Movers({ title, items, positive }: { title: string; items: { symbol: string; change_pct: number }[]; positive: boolean }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</p>
      <ul className="mt-1.5 space-y-1">
        {items.map((m) => (
          <li key={m.symbol} className="flex items-center justify-between text-xs">
            <Link to={`/premium/stocks/${encodeURIComponent(m.symbol)}`} className="font-semibold text-slate-100 hover:underline">{m.symbol}</Link>
            <span className={`font-mono tabular-nums ${tone(positive ? 1 : -1)}`}>{signed(m.change_pct, "%")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// A short recap of the market written from the app's own numbers (by the AI if its text passes the checks, otherwise by rules).
export default function DailySummary() {
  const query = useQuery({ queryKey: ["premium-summary"], queryFn: () => apiGet<MarketSummary>("/premium/summary"), refetchInterval: 300_000, retry: false });
  const d = query.data;
  return (
    <section data-testid="daily-summary" className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-heading text-base text-slate-100">Market recap</h2>
          {d && <MarketBadge market={d.market} />}
          {d && <span data-testid="summary-source" title={d.source === "AI" ? "Written by AI from the figures below; every number was checked against them." : "Written by fixed rules from the figures below."} className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${d.source === "AI" ? "border-violet-400/30 bg-violet-400/10 text-violet-200" : "border-slate-500/30 bg-slate-500/10 text-slate-300"}`}>{d.source === "AI" ? "AI-written" : "Rules-written"}</span>}
        </div>
        {d && <span className="text-[10px] text-slate-500">Generated {clockTime(d.generated_at)}</span>}
      </div>
      {query.isPending && <p className="mt-3 text-xs text-slate-500">Loading…</p>}
      {query.isError && <p className="mt-3 text-xs text-slate-500">The recap is unavailable right now.</p>}
      {d && (
        <>
          <p data-testid="summary-text" className="mt-3 text-sm leading-relaxed text-slate-200">{d.text}</p>
          {d.facts.stocks_with_prices > 0 && (
            <div className="mt-4 grid gap-4 border-t border-[#202b42] pt-3 sm:grid-cols-3">
              <Movers title="Top gainers" items={d.facts.top_gainers.slice(0, 4)} positive />
              <Movers title="Top losers" items={d.facts.top_losers.slice(0, 4)} positive={false} />
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Breadth and signals</p>
                <p className="mt-1.5 text-xs text-slate-300">{d.facts.advancers} up · {d.facts.decliners} down</p>
                <p className="text-xs text-slate-300">{d.facts.signals_bullish} bullish · {d.facts.signals_bearish} bearish signals</p>
                {d.facts.volume_spikes.length > 0 && <p className="mt-1 text-xs text-amber-200">Unusual volume: {d.facts.volume_spikes.slice(0, 3).map((v) => `${v.symbol} ${v.relative_volume}x`).join(", ")}</p>}
              </div>
            </div>
          )}
          <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">{d.note} Shared with all members and refreshed about every 15 minutes while the market is open.</p>
        </>
      )}
    </section>
  );
}
