import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import AnalysisView from "@/components/premium/AnalysisView";
import { MarketBadge } from "@/components/premium/AnalysisPanels";
import { apiGet } from "@/lib/api";
import { INDEX_LABEL, PREMIUM_INDICES, pollMs, price, signed, tone, type Detail, type IndexRow, type IndexSymbol4, type Interval } from "@/lib/premium";

export default function PremiumIndices() {
  const [symbol, setSymbol] = useState<IndexSymbol4>("NIFTY");
  const [interval, setIntervalValue] = useState<Interval>(1);
  const strip = useQuery({ queryKey: ["premium-indices"], queryFn: () => apiGet<{ indices: IndexRow[] }>("/premium/indices"), refetchInterval: 3000, retry: false });
  const detail = useQuery({
    queryKey: ["premium-index", symbol, interval],
    queryFn: () => apiGet<Detail>(`/premium/index/${symbol}?interval=${interval}`),
    refetchInterval: (query) => pollMs(query.state.data?.market.state),
    retry: false,
  });
  return (
    <div data-testid="premium-indices" className="space-y-4">
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {PREMIUM_INDICES.map((item) => {
          const row = strip.data?.indices.find((r) => r.symbol === item);
          const q = row?.quote ?? null;
          return (
            <button key={item} type="button" data-testid={`index-card-${item.toLowerCase()}`} aria-pressed={symbol === item} onClick={() => setSymbol(item)} className={`data-hover rounded-xl border p-3 text-left ${symbol === item ? "border-blue-400/50 bg-[#111a2b]" : "border-[#202b42] bg-[#0c0f17]/95 hover:border-[#2f3d5c]"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold tracking-wide text-slate-300">{INDEX_LABEL[item]}</span>
                {row && <MarketBadge market={row.market} />}
              </div>
              <p className="mt-1.5 font-mono text-lg font-bold tabular-nums text-white">{q ? price(q.ltp) : "—"}</p>
              <p className={`font-mono text-[11px] tabular-nums ${tone(q?.change_pct)}`}>{q ? signed(q.change_pct, "%") : row?.market.state === "NO_FEED" ? "No live feed" : "Waiting for a price"}</p>
            </button>
          );
        })}
      </div>
      {detail.isError && <p data-testid="premium-index-error" className="rounded-lg border border-[#202b42] p-4 text-xs text-slate-500">This index is unavailable right now.</p>}
      {detail.data && <AnalysisView detail={detail.data} interval={interval} onInterval={setIntervalValue} />}
      {detail.isPending && <p className="p-4 text-xs text-slate-500">Loading live data…</p>}
    </div>
  );
}
