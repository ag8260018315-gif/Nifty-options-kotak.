import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { MarketBadge } from "@/components/premium/AnalysisPanels";
import { apiGet } from "@/lib/api";
import { heatColor, pollMs, price, signed, tone, type SectorRow, type SectorsResponse } from "@/lib/premium";

type SortKey = "change" | "breadth" | "volume";

function breadth(s: SectorRow): number {
  const n = s.advancers + s.decliners;
  return n ? s.advancers / n : 0;
}

// Which sectors are moving today: a tile per sector coloured by its average change, and a ranking table. Click a sector for its stocks.
export default function SectorHeatmap() {
  const [open, setOpen] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("change");
  const query = useQuery({ queryKey: ["premium-sectors"], queryFn: () => apiGet<SectorsResponse>("/premium/sectors"), refetchInterval: (q) => pollMs(q.state.data?.market.state), retry: false });
  const data = query.data;
  const rows = [...(data?.sectors ?? [])].sort((a, b) => sort === "change" ? (b.avg_change_pct ?? -99) - (a.avg_change_pct ?? -99) : sort === "breadth" ? breadth(b) - breadth(a) : (b.avg_relative_volume ?? 0) - (a.avg_relative_volume ?? 0));
  const selected = rows.find((s) => s.sector === open) ?? null;
  return (
    <div data-testid="sector-heatmap" className="space-y-4">
      <section className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-3 sm:p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2"><h1 className="font-heading text-base text-slate-100">Sectors</h1>{data && <MarketBadge market={data.market} />}</div>
          <select data-testid="sector-sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Rank sectors by" className="h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300">
            <option value="change">Best average change</option>
            <option value="breadth">Most stocks rising</option>
            <option value="volume">Highest relative volume</option>
          </select>
        </div>
        {query.isError && <p className="mt-3 text-xs text-slate-500">Sector data is unavailable right now.</p>}
        {query.isPending && <p className="mt-3 text-xs text-slate-500">Loading…</p>}
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {rows.map((s) => (
            <button key={s.sector} type="button" data-testid={`sector-tile-${s.sector}`} aria-pressed={open === s.sector} onClick={() => setOpen(open === s.sector ? null : s.sector)} style={{ backgroundColor: heatColor(s.avg_change_pct) }} className={`rounded-lg border p-3 text-left transition-colors ${open === s.sector ? "border-white/60" : "border-white/10 hover:border-white/30"}`}>
              <p className="truncate text-xs font-semibold text-white">{s.sector}</p>
              <p className="mt-1 font-mono text-lg font-bold tabular-nums text-white">{s.avg_change_pct === null ? "—" : signed(s.avg_change_pct, "%")}</p>
              <p className="text-[10px] text-slate-200/80">{s.advancers} up · {s.decliners} down · {s.stocks} stocks</p>
            </button>
          ))}
        </div>
        {data && <p data-testid="sector-note" className="mt-3 text-[10px] leading-relaxed text-slate-500">{data.note}</p>}
      </section>

      {selected && (
        <section data-testid="sector-detail" className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-3 sm:p-4">
          <h2 className="font-heading text-base text-slate-100">{selected.sector}: {selected.with_prices} of {selected.stocks} stocks have a price</h2>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {selected.members.map((m) => (
              <Link key={m.symbol} to={`/premium/stocks/${encodeURIComponent(m.symbol)}`} data-testid={`sector-stock-${m.symbol}`} style={{ backgroundColor: heatColor(m.change_pct) }} className="rounded-lg border border-white/10 p-2.5 hover:border-white/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">
                <p className="text-xs font-semibold text-white">{m.symbol}</p>
                <p className="truncate text-[10px] text-slate-200/70">{m.name}</p>
                <p className="mt-1 font-mono text-xs tabular-nums text-white">{price(m.ltp)} <span className="text-[10px]">{signed(m.change_pct, "%")}</span></p>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section className="overflow-x-auto rounded-xl border border-[#202b42] bg-[#0c0f17]/95">
        <table data-testid="sector-table" className="w-full min-w-[640px] text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-slate-500">
            <tr><th className="px-3 py-2">#</th><th className="px-3 py-2">Sector</th><th className="px-3 py-2 text-right">Avg change</th><th className="px-3 py-2 text-right">Up / down</th><th className="px-3 py-2 text-right">Bullish / bearish</th><th className="px-3 py-2 text-right">Rel. vol</th><th className="px-3 py-2">Leaders</th><th className="px-3 py-2">Laggards</th></tr>
          </thead>
          <tbody>
            {rows.map((s, i) => (
              <tr key={s.sector} data-testid={`sector-row-${s.sector}`} className="border-t border-[#161e30]">
                <td className="px-3 py-2 text-slate-500">{i + 1}</td>
                <td className="px-3 py-2 font-semibold text-slate-100">{s.sector}</td>
                <td className={`px-3 py-2 text-right font-mono tabular-nums ${tone(s.avg_change_pct)}`}>{signed(s.avg_change_pct, "%")}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-300">{s.advancers} / {s.decliners}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-300">{s.bullish} / {s.bearish}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-300">{s.avg_relative_volume ?? "—"}</td>
                <td className="px-3 py-2 text-emerald-300/90">{s.leaders.join(", ") || "—"}</td>
                <td className="px-3 py-2 text-rose-300/90">{s.laggards.filter((x) => !s.leaders.includes(x)).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
