import { ago, type NewsBlock, type NewsItem, type Sentiment } from "@/lib/premium";
import { useStockAnnouncements, useStockNews } from "@/lib/premiumData";

const TONE: Record<Sentiment["tone"], string> = {
  Positive: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  Negative: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  Mixed: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  Neutral: "border-slate-500/30 bg-slate-500/10 text-slate-400",
};

function Chips({ item }: { item: NewsItem }) {
  const s = item.sentiment;
  if (!s) return null;
  const words = [...s.positive_words, ...s.negative_words];
  return (
    <span className="ml-2 inline-flex flex-wrap items-center gap-1 align-middle">
      <span data-testid="tone-chip" title={words.length ? `Words seen: ${words.join(", ")}` : "No tone words found"} className={`rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${TONE[s.tone]}`}>{s.tone}</span>
      {s.topic !== "General" && <span className="rounded-full border border-[#2a364f] px-1.5 py-0.5 text-[9px] text-slate-400">{s.topic}</span>}
    </span>
  );
}

function Block({ title, block, pending, failed, empty, testId }: { title: string; block: NewsBlock | undefined; pending: boolean; failed: boolean; empty: string; testId: string }) {
  const summary = block?.summary;
  return (
    <div data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</p>
        {block && <span className="text-[10px] text-slate-600">{block.provider}</span>}
      </div>
      {summary && summary.items > 0 && <p data-testid={`${testId}-summary`} className="mt-1 text-[10px] text-slate-500">Keyword reading: {summary.counts.Positive} positive · {summary.counts.Negative} negative · {summary.counts.Mixed} mixed · {summary.counts.Neutral} neutral</p>}
      {pending && <p className="mt-2 text-xs text-slate-500">Loading…</p>}
      {(failed || (block && block.status !== "ok")) && <p className="mt-2 text-xs text-slate-500">Unavailable right now. Nothing is shown rather than guessing.</p>}
      {block && block.status === "ok" && block.items.length === 0 && <p className="mt-2 text-xs text-slate-500">{empty}</p>}
      {block && block.status === "ok" && block.items.length > 0 && (
        <ul className="mt-2 space-y-2.5">
          {block.items.map((item, i) => (
            <li key={`${i}-${item.title}`}>
              {item.link ? <a href={item.link} target="_blank" rel="noopener noreferrer" className="text-xs leading-snug text-sky-300 underline-offset-2 hover:underline">{item.title}</a> : <span className="text-xs leading-snug text-slate-200">{item.title}</span>}
              <Chips item={item} />
              <p className="text-[10px] text-slate-500">{[item.source, ago(item.published_at)].filter(Boolean).join(" · ")}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Exchange announcements and recent headlines for one stock, each with a keyword reading of its tone. As published; not verified.
export default function StockNews({ symbol, name }: { symbol: string; name: string }) {
  const news = useStockNews(symbol);
  const ann = useStockAnnouncements(symbol);
  return (
    <div data-testid="stock-news" className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3 md:col-span-2">
      <p className="text-xs font-semibold text-slate-300">Announcements and news about {name}</p>
      <div className="mt-3 grid gap-6 md:grid-cols-2">
        <Block testId="stock-announcements" title="Exchange announcements" block={ann.data?.announcements} pending={ann.isPending} failed={ann.isError} empty="No recent announcements found." />
        <Block testId="stock-headlines" title="Headlines" block={news.data?.news} pending={news.isPending} failed={news.isError} empty="No recent headlines found for this stock." />
      </div>
      <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">{news.data?.note ?? ann.data?.note ?? "Shown as published; not verified by this app."} {ann.data?.note ?? ""}</p>
    </div>
  );
}
