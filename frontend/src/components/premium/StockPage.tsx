import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import AnalysisView from "@/components/premium/AnalysisView";
import { MarketBadge } from "@/components/premium/AnalysisPanels";
import Flash from "@/components/premium/Flash";
import { PerformanceCard } from "@/components/premium/StockPanels";
import StockNews from "@/components/premium/StockNews";
import WatchlistMenu from "@/components/premium/WatchlistMenu";
import { ApiError, apiGet } from "@/lib/api";
import { DEFAULT_EMA, INTERVAL_OPTIONS, pollMs, price, signed, tickAge, tone, validEma, whole, type Detail, type Interval } from "@/lib/premium";
import { keepPreviousData, useSessionState } from "@/lib/premiumData";

function StockHeader({ detail }: { detail: Detail }) {
  const quote = detail.quote;
  const market = detail.market;
  return (
    <div data-testid="stock-header" className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 data-testid="stock-title" className="font-heading text-xl font-semibold text-white sm:text-2xl">{detail.name}</h1>
            <span data-testid="stock-symbol" className="rounded-md border border-[#2a364f] bg-[#0e131d] px-2 py-0.5 font-mono text-xs font-semibold text-slate-200">{detail.symbol}</span>
            {detail.sector && <span data-testid="stock-sector" className="rounded-md border border-[#2a364f] px-2 py-0.5 text-[11px] text-slate-400">{detail.sector}</span>}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <MarketBadge market={market} />
            <span data-testid="stock-age" className="text-[11px] text-slate-500">Last price {tickAge(market.tick_age_seconds)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <WatchlistMenu symbol={detail.symbol} />
          <Link to={`/premium/compare?symbols=${encodeURIComponent(detail.symbol)}`} data-testid="stock-compare" className="inline-flex h-8 items-center rounded-md border border-[#26334b] px-3 text-xs text-slate-300 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">Compare</Link>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p data-testid="quote-ltp" className="font-mono text-3xl font-bold tabular-nums text-white sm:text-4xl">{quote ? <Flash value={quote.ltp}>{price(quote.ltp)}</Flash> : "—"}</p>
          <p data-testid="quote-change" className={`mt-1 font-mono text-sm tabular-nums ${tone(quote?.change)}`}>{quote ? `${signed(quote.change)} (${signed(quote.change_pct, "%")})` : market.message}</p>
          {quote && <p className="mt-1 text-[11px] text-slate-500">{market.message}</p>}
        </div>
        {quote && (
          <dl className="grid grid-cols-3 gap-x-6 gap-y-2 text-[11px] sm:grid-cols-6">
            {([["Open", price(quote.open)], ["High", price(quote.high)], ["Low", price(quote.low)], ["Prev close", price(quote.prev_close)], ["Volume", whole(quote.volume)], ["VWAP", price(quote.vwap)]] as const).map(([label, value]) => (
              <div key={label}>
                <dt className="text-slate-500">{label}</dt>
                <dd data-testid={`quote-${label.toLowerCase().replace(" ", "-")}`} className="font-mono tabular-nums text-slate-200">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}

// A dedicated page for one stock: live price and status, the interactive chart, the signal engine, its tested history and the news.
export default function StockPage({ symbol }: { symbol: string }) {
  const [savedInterval, setSavedInterval] = useSessionState<string>("stock-interval", "5");
  const [savedEma, setSavedEma] = useSessionState<string>("stock-ema", `${DEFAULT_EMA[0]},${DEFAULT_EMA[1]}`);
  const requested = Number(savedInterval);
  const interval = (INTERVAL_OPTIONS.some((o) => o.value === requested) ? requested : 5) as Interval;
  const [fast, slow] = savedEma.split(",").map(Number);
  const ema: [number, number] = validEma(fast, slow) === null ? [fast, slow] : [DEFAULT_EMA[0], DEFAULT_EMA[1]];
  const setIntervalValue = (value: Interval) => setSavedInterval(String(value));
  const setEma = (value: [number, number]) => setSavedEma(`${value[0]},${value[1]}`);
  const detail = useQuery({
    queryKey: ["premium-stock", symbol, interval, ema[0], ema[1]],
    queryFn: () => apiGet<Detail>(`/premium/stock/${encodeURIComponent(symbol)}?interval=${interval}&ema_fast=${ema[0]}&ema_slow=${ema[1]}`),
    refetchInterval: (query) => pollMs(query.state.data?.market.state),
    retry: false,
    placeholderData: keepPreviousData, // keep the chart while a new timeframe or EMA loads...
  });
  const data = detail.data && detail.data.symbol === symbol ? detail.data : null; // ...but never show another stock's data
  const unknown = detail.error instanceof ApiError && detail.error.status === 404;

  return (
    <div data-testid="stock-page" className="space-y-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-xs">
        <Link to="/premium/stocks" data-testid="back-to-stocks" className="rounded-md border border-[#26334b] px-3 py-1.5 text-slate-300 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">← All stocks</Link>
        <span className="font-mono text-slate-500">{symbol}</span>
      </nav>
      {unknown && <p data-testid="stock-unknown" role="alert" className="rounded-lg border border-[#202b42] p-4 text-sm text-slate-400">“{symbol}” is not one of the supported stocks. Go back to the list and pick one.</p>}
      {detail.isError && !unknown && !data && (
        <div className="rounded-lg border border-[#202b42] p-4 text-sm text-slate-400">
          This stock is unavailable right now.
          <button type="button" onClick={() => void detail.refetch()} className="ml-3 rounded-md border border-[#26334b] px-3 py-1 text-xs text-slate-200 hover:bg-[#1a2336]">Try again</button>
        </div>
      )}
      {!data && !detail.isError && <p className="p-4 text-xs text-slate-500">Loading {symbol}…</p>}
      {data && (
        <>
          <StockHeader detail={data} />
          <AnalysisView
            detail={data}
            interval={interval}
            onInterval={setIntervalValue}
            ema={ema}
            onEma={setEma}
            hideHeader
            performance={data.performance ? <PerformanceCard performance={data.performance} name={data.name} /> : undefined}
          >
            <StockNews symbol={data.symbol} name={data.name} />
          </AnalysisView>
        </>
      )}
    </div>
  );
}
