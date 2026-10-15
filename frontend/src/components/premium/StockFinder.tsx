import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { apiGet } from "@/lib/api";
import type { DirectoryResponse } from "@/lib/premium";

// Search every NSE stock by name or symbol. Stocks on the live feed open with live prices; every other stock opens an end-of-day chart.
export default function StockFinder() {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), 250); // wait for a pause in typing before asking the server
    return () => clearTimeout(timer);
  }, [text]);
  const found = useQuery({
    queryKey: ["premium-directory", query],
    queryFn: () => apiGet<DirectoryResponse>(`/premium/directory?q=${encodeURIComponent(query)}&limit=12`),
    enabled: query.length > 0,
    staleTime: 60_000,
    retry: false,
  });
  const data = query.length > 0 ? found.data : undefined;
  return (
    <section data-testid="stock-finder" aria-label="Find any NSE stock" className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-base text-slate-100">Find any NSE stock</h2>
        {data && <span data-testid="finder-total" className="text-[10px] text-slate-500">{data.loaded ? `${data.total.toLocaleString("en-IN")} NSE stocks searched` : `${data.live_count} live stocks searched`}</span>}
      </div>
      <input data-testid="finder-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a company name or symbol, for example Zomato or TATA" aria-label="Find any NSE stock by name or symbol" className="mt-2 h-9 w-full rounded-md border border-[#2a364f] bg-[#0e131d] px-3 text-sm text-slate-200 placeholder:text-slate-600" />
      {query.length > 0 && found.isError && <p className="mt-2 text-xs text-slate-500">Search is unavailable right now.</p>}
      {data && data.items.length === 0 && <p data-testid="finder-none" className="mt-2 text-xs text-slate-500">No stock matches “{query}”.</p>}
      {data && data.items.length > 0 && (
        <ul data-testid="finder-results" className="mt-2 divide-y divide-[#161e30] rounded-md border border-[#202b42]">
          {data.items.map((item) => (
            <li key={item.symbol}>
              <Link to={`/premium/stocks/${encodeURIComponent(item.symbol)}`} data-testid={`finder-row-${item.symbol}`} className="flex items-center justify-between gap-3 px-3 py-2 text-xs hover:bg-[#101827] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">
                <span className="min-w-0">
                  <span className="font-semibold text-slate-100">{item.symbol}</span>
                  <span className="ml-2 truncate text-slate-500">{item.name}</span>
                </span>
                {item.live
                  ? <span className="shrink-0 rounded-full border border-emerald-500/35 bg-emerald-950/70 px-2 py-0.5 text-[9px] font-bold tracking-[0.1em] text-emerald-300">LIVE</span>
                  : <span className="shrink-0 rounded-full border border-sky-500/35 bg-sky-950/70 px-2 py-0.5 text-[9px] font-bold tracking-[0.1em] text-sky-300">END OF DAY</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && !data.loaded && <p data-testid="finder-partial" className="mt-2 text-[11px] leading-relaxed text-amber-200/80">The full list of NSE stocks has not been loaded yet, so this search covers only the {data.live_count} stocks on the live feed. The owner can load every stock with tools/import_upstox_all_stocks.py.</p>}
      {data && data.loaded && <p className="mt-2 text-[10px] leading-relaxed text-slate-600">“End of day” stocks are not on the live feed: they have daily, weekly and monthly charts from stored candles, and no live price.</p>}
    </section>
  );
}
