import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { MarketBadge } from "@/components/premium/AnalysisPanels";
import Flash from "@/components/premium/Flash";
import PremiumBreakouts from "@/components/premium/PremiumBreakouts";
import { BiasPill } from "@/components/premium/StockPanels";
import { apiGet } from "@/lib/api";
import { biasFromAction, pollMs, price, signed, tone, whole, type Bias, type MarketInfo, type StockRow } from "@/lib/premium";
import { FAVOURITES, useSessionState, useWatchlists } from "@/lib/premiumData";

type SortKey = "symbol" | "gain" | "loss" | "volume" | "rvol" | "bullish" | "bearish";

const SORTS: { value: SortKey; label: string }[] = [
  { value: "symbol", label: "A to Z" },
  { value: "gain", label: "Top gainers" },
  { value: "loss", label: "Top losers" },
  { value: "volume", label: "Volume" },
  { value: "rvol", label: "Relative volume" },
  { value: "bullish", label: "Most bullish score" },
  { value: "bearish", label: "Most bearish score" },
];

const SORT_KEY: Record<SortKey, (r: StockRow) => number | string> = {
  symbol: (r) => r.symbol,
  gain: (r) => -(r.quote?.change_pct ?? -999),
  loss: (r) => r.quote?.change_pct ?? 999,
  volume: (r) => -(r.quote?.volume ?? 0),
  rvol: (r) => -(r.signal.relative_volume ?? -1),
  bullish: (r) => (r.quote ? -r.signal.score : 999),
  bearish: (r) => (r.quote ? r.signal.score : 999),
};

const MAX_COMPARE = 4;
const selectClass = "h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300";

function RowSignal({ row }: { row: StockRow }) {
  if (!row.quote) return <span className="text-slate-600">—</span>;
  if (row.signal.action === "BUILDING") return <span title="Not enough closed candles yet for a signal." className="text-[10px] text-sky-300">building…</span>;
  return <BiasPill bias={biasFromAction(row.signal.action)} />;
}

export default function PremiumStocks() {
  const navigate = useNavigate();
  const [search, setSearch] = useSessionState<string>("stocks-search", "");
  const [sector, setSector] = useSessionState<string>("stocks-sector", "All");
  const [bias, setBias] = useSessionState<"All" | Bias>("stocks-bias", "All");
  const [listName, setListName] = useSessionState<string>("stocks-list", "All");
  const [sort, setSort] = useSessionState<SortKey>("stocks-sort", "symbol");
  const [picked, setPicked] = useState<string[]>([]);
  const [hint, setHint] = useState<string | null>(null);
  const lists = useWatchlists();
  const list = useQuery({ queryKey: ["premium-stocks"], queryFn: () => apiGet<{ market: MarketInfo; count: number; configured: number; stocks: StockRow[] }>("/premium/stocks"), refetchInterval: (query) => pollMs(query.state.data?.market.state), retry: false });

  const all = list.data?.stocks;
  const sectors = useMemo(() => Array.from(new Set((all ?? []).map((r) => r.sector).filter(Boolean))).sort((a, b) => a.localeCompare(b)), [all]);
  const listNames = Object.keys(lists.lists).sort((a, b) => (a === FAVOURITES ? -1 : b === FAVOURITES ? 1 : a.localeCompare(b)));

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const members = listName !== "All" ? new Set(lists.lists[listName] ?? []) : null;
    const filtered = (all ?? []).filter((r) => {
      if (needle && !r.symbol.toLowerCase().includes(needle) && !r.name.toLowerCase().includes(needle)) return false;
      if (sector !== "All" && r.sector !== sector) return false;
      if (members && !members.has(r.symbol)) return false;
      if (bias !== "All" && (!r.quote || biasFromAction(r.signal.action) !== bias)) return false;
      return true;
    });
    const key = SORT_KEY[sort];
    return [...filtered].sort((a, b) => {
      const ka = key(a);
      const kb = key(b);
      const order = typeof ka === "string" && typeof kb === "string" ? ka.localeCompare(kb) : Number(ka) - Number(kb);
      return order || a.symbol.localeCompare(b.symbol);
    });
  }, [all, search, sector, bias, listName, sort, lists.lists]);

  const togglePick = (symbol: string) => {
    setHint(null);
    if (picked.includes(symbol)) {
      setPicked(picked.filter((s) => s !== symbol));
    } else if (picked.length >= MAX_COMPARE) {
      setHint(`You can compare up to ${MAX_COMPARE} stocks at a time.`);
    } else {
      setPicked([...picked, symbol]);
    }
  };

  const filtersOn = search !== "" || sector !== "All" || bias !== "All" || listName !== "All";

  return (
    <div data-testid="premium-stocks" className="space-y-4">
      <PremiumBreakouts />

      <section className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95">
        <div className="space-y-3 border-b border-[#202b42] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-heading text-base text-slate-100">Indian stocks</h2>
              {list.data && <MarketBadge market={list.data.market} />}
              {list.data && <span data-testid="stocks-count" className="text-[10px] text-slate-500">{rows.length} shown · {list.data.configured} stocks · {list.data.count} with prices</span>}
            </div>
            {filtersOn && <button type="button" data-testid="stocks-clear" onClick={() => { setSearch(""); setSector("All"); setBias("All"); setListName("All"); }} className="rounded-md px-2 py-1 text-[11px] text-sky-300 hover:bg-[#1a2336]">Clear filters</button>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input data-testid="stock-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name or symbol" aria-label="Search name or symbol" className="h-8 w-full rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 text-xs text-slate-200 placeholder:text-slate-600 sm:w-52" />
            <select data-testid="stock-sector" value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Filter by sector" className={selectClass}>
              <option value="All">All sectors</option>
              {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select data-testid="stock-bias" value={bias} onChange={(e) => setBias(e.target.value as "All" | Bias)} aria-label="Filter by signal" className={selectClass}>
              <option value="All">Any signal</option>
              <option value="Bullish">Bullish</option>
              <option value="Bearish">Bearish</option>
              <option value="Neutral">Neutral</option>
            </select>
            <select data-testid="stock-list" value={listName} onChange={(e) => setListName(e.target.value)} aria-label="Show a watchlist" className={selectClass}>
              <option value="All">All stocks</option>
              {listNames.map((n) => <option key={n} value={n}>★ {n} ({(lists.lists[n] ?? []).length})</option>)}
            </select>
            <select data-testid="stock-sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort stocks" className={selectClass}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          {lists.failed && <p className="text-[11px] text-slate-500">Watchlists couldn't be loaded right now, so the star buttons are paused.</p>}
        </div>
        {list.data && list.data.count === 0 && (
          <p data-testid="stocks-no-prices" className="border-b border-[#202b42] px-3 py-2 text-[11px] leading-relaxed text-slate-500">No prices yet. Prices appear from the live Kotak feed during market hours (09:15–15:30 IST), and the last received prices are kept for after hours. Nothing is shown until real prices arrive.</p>
        )}
        <div className="max-h-[560px] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-10 bg-[#0c0f17] text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="w-8 px-2 py-2"><span className="sr-only">Watchlist</span></th>
                <th className="px-2 py-2 sm:px-3">Stock</th>
                <th className="hidden px-2 py-2 sm:px-3 lg:table-cell">Sector</th>
                <th className="px-2 py-2 sm:px-3 text-right">Price</th>
                <th className="hidden px-2 py-2 sm:px-3 text-right sm:table-cell">Change</th>
                <th className="hidden px-2 py-2 sm:px-3 text-right sm:table-cell">Volume</th>
                <th className="hidden px-2 py-2 sm:px-3 text-right md:table-cell">Rel. vol</th>
                <th className="hidden px-2 py-2 sm:px-3 xl:table-cell">Trend</th>
                <th className="px-2 py-2 sm:px-3 text-right">Signal</th>
                <th className="w-10 px-1.5 py-2 text-center sm:px-2"><span className="sm:hidden" title="Compare">vs</span><span className="hidden sm:inline">Compare</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const starred = lists.has(FAVOURITES, r.symbol);
                return (
                  <tr key={r.symbol} data-testid={`stock-row-${r.symbol}`} onClick={() => navigate(`/premium/stocks/${encodeURIComponent(r.symbol)}`)} className="cursor-pointer border-t border-[#161e30] hover:bg-[#101827]">
                    <td className="px-1.5 py-2 text-center sm:px-2">
                      <button type="button" data-testid={`star-${r.symbol}`} aria-pressed={starred} aria-label={`${starred ? "Remove" : "Add"} ${r.symbol} ${starred ? "from" : "to"} Favourites`} disabled={!lists.ready} onClick={(e) => { e.stopPropagation(); lists.toggle(FAVOURITES, r.symbol); }} className={`text-base leading-none ${starred ? "text-amber-300" : "text-slate-600 hover:text-amber-200"} disabled:opacity-40`}>{starred ? "★" : "☆"}</button>
                    </td>
                    <td className="px-2 py-2 sm:px-3">
                      <Link to={`/premium/stocks/${encodeURIComponent(r.symbol)}`} onClick={(e) => e.stopPropagation()} className="font-semibold text-slate-100 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">{r.symbol}</Link>
                      <span className="block max-w-[6.5rem] truncate text-[10px] text-slate-500 sm:max-w-[16rem]">{r.name}</span>
                    </td>
                    <td className="hidden px-2 py-2 sm:px-3 text-slate-400 lg:table-cell">{r.sector}</td>
                    <td className="px-2 py-2 sm:px-3 text-right font-mono tabular-nums text-white">
                      {r.quote ? <Flash value={r.quote.ltp}>{price(r.quote.ltp)}</Flash> : "—"}
                      <span className={`block text-[10px] sm:hidden ${tone(r.quote?.change_pct)}`}>{r.quote ? signed(r.quote.change_pct, "%") : ""}</span>
                    </td>
                    <td className={`hidden px-2 py-2 sm:px-3 text-right font-mono tabular-nums sm:table-cell ${tone(r.quote?.change_pct)}`}>{signed(r.quote?.change_pct, "%")}</td>
                    <td className="hidden px-2 py-2 sm:px-3 text-right font-mono tabular-nums text-slate-400 sm:table-cell">{whole(r.quote?.volume)}</td>
                    <td className={`hidden px-2 py-2 sm:px-3 text-right font-mono tabular-nums md:table-cell ${(r.signal.relative_volume ?? 0) >= 2 ? "text-amber-300" : "text-slate-400"}`}>{r.signal.relative_volume != null ? `${r.signal.relative_volume}x` : "—"}</td>
                    <td className="hidden px-2 py-2 sm:px-3 text-slate-400 xl:table-cell">{r.quote ? r.signal.trend.toLowerCase() : "—"}</td>
                    <td className="px-2 py-2 sm:px-3 text-right"><RowSignal row={r} /></td>
                    <td className="px-1.5 py-2 text-center sm:px-2">
                      <input type="checkbox" data-testid={`pick-${r.symbol}`} aria-label={`Compare ${r.symbol}`} checked={picked.includes(r.symbol)} onClick={(e) => e.stopPropagation()} onChange={() => togglePick(r.symbol)} className="size-3.5 accent-sky-400" />
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr><td colSpan={10} className="px-3 py-8 text-center text-slate-500">{list.isError ? "Stocks are unavailable right now." : list.isPending ? "Loading…" : filtersOn ? "No stock matches these filters." : "No stocks to show."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {(picked.length > 0 || hint) && (
          <div data-testid="compare-bar" className="flex flex-wrap items-center justify-between gap-2 border-t border-[#202b42] bg-[#0e131d] px-3 py-2 text-xs">
            <span className="text-slate-300">{picked.length > 0 ? `Compare ${picked.join(", ")} (${picked.length}/${MAX_COMPARE})` : ""}{hint && <span role="status" className="ml-2 text-amber-300">{hint}</span>}</span>
            <span className="flex items-center gap-2">
              <button type="button" data-testid="compare-clear" onClick={() => { setPicked([]); setHint(null); }} className="rounded-md border border-[#26334b] px-3 py-1 text-slate-300 hover:bg-[#1a2336]">Clear</button>
              {picked.length >= 2 ? (
                <Link to={`/premium/compare?symbols=${picked.map(encodeURIComponent).join(",")}`} data-testid="compare-go" className="rounded-md bg-sky-400 px-3 py-1 font-semibold text-[#06121c] hover:bg-sky-300">Compare</Link>
              ) : (
                <span className="rounded-md bg-[#141c2b] px-3 py-1 text-slate-500">Pick at least 2</span>
              )}
            </span>
          </div>
        )}
        <p className="border-t border-[#202b42] px-3 py-2 text-[10px] leading-relaxed text-slate-600">The list signal is a quick read of recent candles. Open a stock for the full signal engine, its trade setup and its tested history.</p>
      </section>
    </div>
  );
}
