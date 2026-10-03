import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import AnalysisView from "@/components/premium/AnalysisView";
import { ActionPill, MarketBadge } from "@/components/premium/AnalysisPanels";
import { apiGet } from "@/lib/api";
import { pollMs, price, signed, tone, whole, type Detail, type Interval, type MarketInfo, type StockRow } from "@/lib/premium";

type SortKey = "symbol" | "change" | "volume" | "score";

function Flash({ value, children }: { value: number; children: ReactNode }) {
  const previous = useRef(value);
  const [dir, setDir] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    if (value === previous.current) return;
    setDir(value > previous.current ? "up" : "down");
    previous.current = value;
    const timer = window.setTimeout(() => setDir(null), 700);
    return () => window.clearTimeout(timer);
  }, [value]);
  return <span className={`rounded px-1 transition-colors duration-500 ${dir === "up" ? "bg-emerald-500/25" : dir === "down" ? "bg-rose-500/25" : ""}`}>{children}</span>;
}

export default function PremiumStocks() {
  const [selected, setSelected] = useState<string | null>(null);
  const [interval, setIntervalValue] = useState<Interval>(1);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("symbol");
  const list = useQuery({ queryKey: ["premium-stocks"], queryFn: () => apiGet<{ market: MarketInfo; count: number; configured: number; stocks: StockRow[] }>("/premium/stocks"), refetchInterval: (query) => pollMs(query.state.data?.market.state), retry: false });
  const picks = useQuery({ queryKey: ["premium-picks"], queryFn: () => apiGet<{ title: string; note: string; stocks: StockRow[] }>("/premium/stocks/opportunities"), refetchInterval: 6000, retry: false });
  const detail = useQuery({
    queryKey: ["premium-stock", selected, interval],
    queryFn: () => apiGet<Detail>(`/premium/stock/${encodeURIComponent(selected ?? "")}?interval=${interval}`),
    enabled: selected !== null,
    refetchInterval: (query) => pollMs(query.state.data?.market.state),
    retry: false,
  });

  const rows = useMemo(() => {
    const needle = search.trim().toUpperCase();
    const filtered = (list.data?.stocks ?? []).filter((r) => !needle || r.symbol.includes(needle));
    const by: Record<SortKey, (r: StockRow) => number | string> = {
      symbol: (r) => r.symbol,
      change: (r) => -(r.quote.change_pct ?? -999),
      volume: (r) => -(r.quote.volume ?? 0),
      score: (r) => -r.signal.score,
    };
    return [...filtered].sort((a, b) => {
      const ka = by[sort](a);
      const kb = by[sort](b);
      return typeof ka === "string" && typeof kb === "string" ? ka.localeCompare(kb) : Number(ka) - Number(kb);
    });
  }, [list.data, search, sort]);

  return (
    <div data-testid="premium-stocks" className="space-y-4">
      <section data-testid="stock-opportunities" className="rounded-xl border border-emerald-500/20 bg-[#0c0f17]/95 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-heading text-base text-slate-100">Potential buying setups</h2>
          <span className="text-[10px] text-slate-500">Informational · updates live</span>
        </div>
        {picks.data && picks.data.stocks.length > 0 ? (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {picks.data.stocks.map((p) => (
              <li key={p.symbol}>
                <button type="button" onClick={() => setSelected(p.symbol)} className="data-hover w-full rounded-lg border border-[#202b42] bg-[#090d15] p-3 text-left hover:border-emerald-500/40">
                  <div className="flex items-center justify-between"><span className="font-semibold text-slate-100">{p.symbol}</span><ActionPill action="BUY" strength={p.signal.strength} /></div>
                  <p className="mt-1 font-mono text-sm tabular-nums text-white">{price(p.quote.ltp)} <span className={`text-[11px] ${tone(p.quote.change_pct)}`}>{signed(p.quote.change_pct, "%")}</span></p>
                  <p className="mt-1 text-[10px] leading-snug text-slate-500">{p.signal.reasons[0] ?? ""}</p>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-xs text-slate-500">{picks.isError ? "Unavailable right now." : "No stock currently meets the buy criteria, or candles are still being collected."}</p>
        )}
        <p className="mt-3 text-[10px] leading-relaxed text-slate-600">{picks.data?.note ?? "Scored from live trend, momentum, MACD, VWAP, volume and nearby support/resistance. Not advice or a prediction."}</p>
      </section>

      <section className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#202b42] p-3">
          <div className="flex items-center gap-2">
            <h2 className="font-heading text-base text-slate-100">Indian stocks</h2>
            {list.data && <MarketBadge market={list.data.market} />}
            {list.data && <span className="text-[10px] text-slate-500">{list.data.count} of {list.data.configured} with live prices</span>}
          </div>
          <div className="flex items-center gap-2">
            <input data-testid="stock-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search symbol" aria-label="Search symbol" className="h-8 w-36 rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 text-xs text-slate-200 placeholder:text-slate-600" />
            <select data-testid="stock-sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort stocks" className="h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300">
              <option value="symbol">A to Z</option>
              <option value="change">% change</option>
              <option value="volume">Volume</option>
              <option value="score">Signal score</option>
            </select>
          </div>
        </div>
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[#0c0f17] text-[10px] uppercase tracking-wider text-slate-500">
              <tr><th className="px-3 py-2">Symbol</th><th className="px-3 py-2 text-right">Price</th><th className="px-3 py-2 text-right">Change</th><th className="hidden px-3 py-2 text-right sm:table-cell">Volume</th><th className="hidden px-3 py-2 md:table-cell">Trend</th><th className="px-3 py-2 text-right">Signal</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} data-testid={`stock-row-${r.symbol}`} onClick={() => setSelected(r.symbol)} className={`cursor-pointer border-t border-[#161e30] hover:bg-[#101827] ${selected === r.symbol ? "bg-[#111a2b]" : ""}`}>
                  <td className="px-3 py-2 font-semibold text-slate-100">{r.symbol}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-white"><Flash value={r.quote.ltp}>{price(r.quote.ltp)}</Flash></td>
                  <td className={`px-3 py-2 text-right font-mono tabular-nums ${tone(r.quote.change_pct)}`}>{signed(r.quote.change_pct, "%")}</td>
                  <td className="hidden px-3 py-2 text-right font-mono tabular-nums text-slate-400 sm:table-cell">{whole(r.quote.volume)}</td>
                  <td className="hidden px-3 py-2 text-slate-400 md:table-cell">{r.signal.trend.toLowerCase()}</td>
                  <td className="px-3 py-2 text-right"><ActionPill action={r.signal.action} /></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">{list.isError ? "Stocks are unavailable right now." : list.isPending ? "Loading…" : list.data && list.data.configured === 0 ? "No stock list is configured." : "No live stock prices yet. They appear when the Kotak feed is running during market hours."}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {selected && (
        <section data-testid="stock-detail" className="space-y-2">
          <div className="flex items-center justify-between"><h2 className="font-heading text-base text-slate-100">{selected} analysis</h2><button type="button" onClick={() => setSelected(null)} className="rounded-md border border-[#26334b] px-3 py-1 text-xs text-slate-300 hover:bg-[#1a2336]">Close</button></div>
          {detail.isError && <p className="rounded-lg border border-[#202b42] p-4 text-xs text-slate-500">This stock is unavailable right now.</p>}
          {detail.data && <AnalysisView detail={detail.data} interval={interval} onInterval={setIntervalValue} />}
        </section>
      )}
    </div>
  );
}
