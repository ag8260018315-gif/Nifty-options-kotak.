import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import AnalysisView from "@/components/premium/AnalysisView";
import { MarketBadge } from "@/components/premium/AnalysisPanels";
import { apiGet } from "@/lib/api";
import { ago, price, signed, tone, type BreakoutResponse, type BreakoutRow, type Detail, type Interval } from "@/lib/premium";

function Expanded({ row }: { row: BreakoutRow }) {
  const [interval, setIntervalValue] = useState<Interval>(5);
  const detail = useQuery({
    queryKey: ["premium-stock", row.symbol, interval],
    queryFn: () => apiGet<Detail>(`/premium/stock/${encodeURIComponent(row.symbol)}?interval=${interval}`),
    refetchInterval: 4000,
    retry: false,
  });
  return (
    <div data-testid={`breakout-detail-${row.symbol}`} className="space-y-4 border-t border-[#202b42] p-3 sm:p-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Why it is on the list</p>
          <ul className="mt-2 space-y-1.5">{row.setup.reasons.map((r) => <li key={r} className="text-[11px] leading-relaxed text-slate-400">• {r}</li>)}</ul>
          <p className="mt-3 text-[11px] text-slate-500">Support {price(row.setup.support)} · RSI {row.setup.rsi ?? "—"} · based on {row.setup.interval}-minute candles</p>
        </div>
        <div data-testid={`breakout-news-${row.symbol}`}>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Latest news ({row.news.provider})</p>
          {row.news.status === "ok" && row.news.items.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {row.news.items.map((n) => (
                <li key={n.link}>
                  <a href={n.link} target="_blank" rel="noopener noreferrer" className="text-xs leading-snug text-sky-300 underline-offset-2 hover:underline">{n.title}</a>
                  <p className="text-[10px] text-slate-500">{[n.source, ago(n.published_at)].filter(Boolean).join(" · ")}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-slate-500">{row.news.status === "ok" ? "No recent headlines found for this stock." : "News is unavailable right now. Nothing is shown rather than guessing."}</p>
          )}
        </div>
      </div>
      {detail.data && <AnalysisView detail={detail.data} interval={interval} onInterval={setIntervalValue} />}
      {detail.isPending && <p className="text-xs text-slate-500">Loading chart…</p>}
    </div>
  );
}

// A ranked watchlist of stocks sitting just below resistance. The number is a SCORE, never a probability.
export default function PremiumBreakouts() {
  const [open, setOpen] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["premium-breakouts"], queryFn: () => apiGet<BreakoutResponse>("/premium/stocks/breakouts?limit=10"), refetchInterval: 6000, retry: false });
  const data = query.data;
  return (
    <section data-testid="breakout-watchlist" className="rounded-xl border border-amber-400/25 bg-[#0c0f17]/95">
      <div className="space-y-2 border-b border-[#202b42] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-heading text-base text-slate-100">Stocks near resistance (watchlist)</h2>
            {data && <MarketBadge market={data.market} />}
          </div>
          <span data-testid="breakout-not-probability" className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-[10px] font-semibold text-amber-200">Score out of 100 · not a probability</span>
        </div>
        <p className="text-[11px] leading-relaxed text-slate-400">{data?.method ?? "Stocks just below a resistance level, ranked by a transparent score."} Being on this list does not mean a stock will break out.</p>
        {data?.accuracy.backtest ? (
          <div data-testid="breakout-accuracy" className="rounded-lg border border-[#202b42] bg-[#090d15] p-3 text-[11px] leading-relaxed text-slate-400">
            <p>
              <span className="font-semibold text-slate-200">Historical test (past data): </span>
              {data.accuracy.backtest.hit_rate_pct ?? "—"}% of {data.accuracy.backtest.setups} past setups met the success rule
              {data.accuracy.backtest.ci95_low_pct !== null && ` (95% range ${data.accuracy.backtest.ci95_low_pct}–${data.accuracy.backtest.ci95_high_pct}%)`}, over {data.accuracy.backtest.sessions_tested} sessions
              {data.accuracy.backtest.period ? ` (${data.accuracy.backtest.period[0]} to ${data.accuracy.backtest.period[1]})` : ""}.
              {!data.accuracy.validated && <span className="text-amber-300"> Not enough history yet to rely on this.</span>}
            </p>
            {data.accuracy.backtest.hit_rate_pct !== null && (
              <p data-testid="breakout-plain-result" className="mt-2 text-slate-300">In past tests, about <span className="font-semibold text-amber-300">{Math.round(data.accuracy.backtest.hit_rate_pct)} of every 100</span> stocks that were listed met the success rule below. Treat this list as a watchlist, not a prediction.</p>
            )}
            <p className="mt-1 text-slate-500">{data.accuracy.backtest.definition}</p>
            {data.accuracy.backtest.comparison && (() => {
              const c = data.accuracy.backtest.comparison;
              const color = c.verdict === "BETTER" ? "text-emerald-300" : c.verdict === "WORSE" ? "text-rose-300" : "text-amber-300";
              return (
                <div data-testid="breakout-comparison" className="mt-3 rounded-md border border-[#202b42] p-2.5">
                  <p className="font-semibold text-slate-200">Compared with chance</p>
                  <p className={`mt-1 ${color}`}>{c.verdict_text}</p>
                  <p className="mt-1.5 text-slate-400">Reached the target before the stop: listed stocks <span className="text-slate-200">{c.listed_rate_pct ?? "—"}%</span> of {c.listed_setups}; any stock at a random moment <span className="text-slate-200">{c.random_rate_pct ?? "—"}%</span> of {c.random_moments}; stocks near resistance with any score <span className="text-slate-200">{c.near_resistance_rate_pct ?? "—"}%</span> of {c.near_resistance_moments}.</p>
                  <p className="mt-1 text-[10px] text-slate-600">{c.test}</p>
                </div>
              );
            })()}
            <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
              {data.accuracy.backtest.by_score_band.filter((b) => b.setups > 0).map((b) => <span key={b.band}>score {b.band}: <span className="text-slate-200">{b.hit_rate_pct}%</span> of {b.setups}</span>)}
            </p>
            <p className="mt-2 text-slate-500">{data.accuracy.note}</p>
          </div>
        ) : (
          <p data-testid="breakout-accuracy" className="text-[11px] leading-relaxed text-slate-500">Historical validated accuracy: <span className="text-slate-300">Not validated</span>. {data?.accuracy.note ?? "No success rate is claimed."}</p>
        )}
      </div>
      {query.isError && <p className="p-4 text-xs text-slate-500">The watchlist is unavailable right now.</p>}
      {data && data.stocks.length === 0 && (
        <p data-testid="breakout-empty" className="p-4 text-xs leading-relaxed text-slate-500">No stock is within 2% below a resistance level with enough candles right now. Candles build from live prices during market hours (about 35 minutes after the open), so this list is empty when the market is closed.</p>
      )}
      <ol className="divide-y divide-[#161e30]">
        {(data?.stocks ?? []).map((row, index) => (
          <li key={row.symbol} data-testid={`breakout-row-${row.symbol}`}>
            <button type="button" aria-expanded={open === row.symbol} onClick={() => setOpen(open === row.symbol ? null : row.symbol)} className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 p-3 text-left hover:bg-[#101827] sm:p-4">
              <span className="flex size-7 items-center justify-center rounded-full bg-amber-300/15 font-mono text-xs font-bold text-amber-300">{index + 1}</span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-x-3">
                  <span className="font-semibold text-slate-100">{row.symbol}</span>
                  <span className="font-mono text-sm tabular-nums text-white">{price(row.quote.ltp)}</span>
                  <span className={`font-mono text-[11px] tabular-nums ${tone(row.quote.change_pct)}`}>{signed(row.quote.change_pct, "%")}</span>
                </span>
                <span className="mt-1 flex flex-wrap gap-1.5 text-[10px]">
                  <span className="rounded bg-rose-500/10 px-1.5 py-0.5 text-rose-300">{row.setup.distance_pct}% below resistance {price(row.setup.resistance)}</span>
                  <span className="rounded bg-sky-500/10 px-1.5 py-0.5 text-sky-300">volume {row.setup.relative_volume ?? "—"}x</span>
                  <span className="rounded bg-slate-500/10 px-1.5 py-0.5 text-slate-300">{(row.setup.trend ?? "").toLowerCase()}</span>
                </span>
              </span>
              <span className="w-24 text-right sm:w-32">
                <span className="font-mono text-lg font-bold text-amber-300">{row.setup.score}</span><span className="text-[10px] text-slate-500"> /100</span>
                <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-[#141c2b]"><span className="block h-full rounded-full bg-amber-300 transition-all duration-700" style={{ width: `${row.setup.score}%` }} /></span>
              </span>
            </button>
            {open === row.symbol && <Expanded row={row} />}
          </li>
        ))}
      </ol>
      <p className="border-t border-[#202b42] p-3 text-[10px] leading-relaxed text-slate-600">{data?.news_note ?? "Headlines come from Google News and are not verified by this app."} Informational analysis only, not investment advice.</p>
    </section>
  );
}
