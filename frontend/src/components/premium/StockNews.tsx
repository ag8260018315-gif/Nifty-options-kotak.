import { ago } from "@/lib/premium";
import { useStockNews } from "@/lib/premiumData";

// Recent headlines for one stock, as published (Google News). Not verified, not summarised as fact.
export default function StockNews({ symbol, name }: { symbol: string; name: string }) {
  const query = useStockNews(symbol);
  const block = query.data?.news;
  return (
    <div data-testid="stock-news" className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3 md:col-span-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Latest news about {name}</p>
        {block && <span className="text-[10px] text-slate-600">{block.provider}</span>}
      </div>
      {query.isPending && <p className="mt-2 text-xs text-slate-500">Loading headlines…</p>}
      {query.isError && <p className="mt-2 text-xs text-slate-500">News is unavailable right now. Nothing is shown rather than guessing.</p>}
      {block && block.status === "ok" && block.items.length === 0 && <p className="mt-2 text-xs text-slate-500">No recent headlines found for this stock.</p>}
      {block && block.status !== "ok" && <p className="mt-2 text-xs text-slate-500">News is unavailable right now. Nothing is shown rather than guessing.</p>}
      {block && block.status === "ok" && block.items.length > 0 && (
        <ul className="mt-2 grid gap-x-6 gap-y-2.5 md:grid-cols-2">
          {block.items.map((item) => (
            <li key={item.link}>
              <a href={item.link} target="_blank" rel="noopener noreferrer" className="text-xs leading-snug text-sky-300 underline-offset-2 hover:underline">{item.title}</a>
              <p className="text-[10px] text-slate-500">{[item.source, ago(item.published_at)].filter(Boolean).join(" · ")}</p>
            </li>
          ))}
        </ul>
      )}
      {query.data && <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">{query.data.note}</p>}
    </div>
  );
}
