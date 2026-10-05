import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import { Activity, Database, Gauge, Lock, ShieldCheck, Target } from "lucide-react";

import PremiumIndices from "@/components/premium/PremiumIndices";
import PremiumStocks from "@/components/premium/PremiumStocks";
import AlertsPage from "@/components/premium/AlertsPage";
import StockCompare from "@/components/premium/StockCompare";
import StockPage from "@/components/premium/StockPage";
import { apiPost } from "@/lib/api";
import { useAlertEvents } from "@/lib/premiumData";

export interface PremiumUser {
  email: string | null;
  premium: boolean;
  premium_until?: number | null;
}

// The address decides the view, so every stock and comparison has a link that can be bookmarked or shared.
type View = "indices" | "stocks" | "stock" | "compare" | "alerts";

const FEATURES = [
  { icon: Gauge, title: "Advanced live charts", text: "SENSEX, NIFTY 50, BANK NIFTY, FIN NIFTY and every stock, from 1-minute to monthly candles, with 9/20 EMA (or your own periods), Bollinger bands, VWAP, RSI, MACD, volume, support/resistance and candlestick patterns." },
  { icon: Database, title: "129 stocks, a page each", text: "Search, filter by sector, sort, keep watchlists, compare up to four stocks side by side, and open any stock for its live price, status and news." },
  { icon: Target, title: "Signal engine with tested history", text: "Bullish, bearish or neutral with reasons, a buy/sell zone, entry, stop and targets, what would invalidate it, and how the same rule did on past data. Never a promise." },
  { icon: ShieldCheck, title: "Real Kotak data only", text: "Every number comes from the live Kotak Neo feed. Nothing is simulated, and the page says plainly when the market is closed or data is delayed." },
];

function Locked({ email }: { email: string | null }) {
  const [sent, setSent] = useState<"requested" | "already_requested" | null>(null);
  const ask = useMutation({
    mutationFn: () => apiPost<{ status: "requested" | "already_requested" }>("/access/premium-request"),
    onSuccess: (result) => setSent(result.status),
  });
  return (
    <div data-testid="premium-locked" className="mx-auto max-w-3xl space-y-6 py-8">
      <div className="rounded-2xl border border-amber-400/25 bg-[linear-gradient(135deg,rgba(251,191,36,0.07),rgba(255,255,255,0.01))] p-6 sm:p-8">
        <div className="flex items-center gap-2 text-amber-300"><Lock className="size-4" /><span className="text-[11px] font-bold uppercase tracking-[0.2em]">Premium only</span></div>
        <h1 className="mt-3 font-heading text-2xl font-bold text-white sm:text-3xl">Unlock live indices, SENSEX and stock analysis</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">This section is part of the paid Premium plan. Your account{email ? ` (${email})` : ""} doesn't have Premium yet, so no premium data is loaded or shown.</p>
        {sent ? (
          <p data-testid="premium-request-sent" role="status" className="mt-6 rounded-lg border border-emerald-400/25 bg-emerald-400/[0.07] px-4 py-3 text-sm text-emerald-100">{sent === "requested" ? "Request sent. The owner will enable Premium for your account and you'll see it here after you refresh." : "You already asked recently. The owner has your request."}</p>
        ) : (
          <button type="button" data-testid="premium-request" disabled={ask.isPending} onClick={() => ask.mutate()} className="mt-6 h-11 rounded-xl bg-amber-300 px-6 text-sm font-semibold text-[#1a1203] hover:bg-amber-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200/60 disabled:opacity-60">{ask.isPending ? "Sending…" : "Request Premium"}</button>
        )}
        {ask.isError && <p role="alert" className="mt-3 text-xs text-rose-300">That didn't go through. Try again shortly.</p>}
        <p className="mt-3 text-[11px] text-slate-500">Online payment isn't live yet. Premium is switched on by the owner after your request.</p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {FEATURES.map((f) => (
          <li key={f.title} className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-4">
            <f.icon className="size-5 text-amber-300" />
            <p className="mt-2 text-sm font-semibold text-slate-100">{f.title}</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">{f.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Premium({ user }: { user: PremiumUser }) {
  const { symbol } = useParams<{ symbol: string }>();
  const { pathname } = useLocation();
  const view: View = symbol ? "stock" : pathname.startsWith("/premium/alerts") ? "alerts" : pathname.startsWith("/premium/compare") ? "compare" : pathname.startsWith("/premium/stocks") ? "stocks" : "indices";
  const { unread } = useAlertEvents();
  const activeTab = view === "indices" ? "indices" : view === "alerts" ? "alerts" : "stocks";
  const until = user.premium_until ? new Date(user.premium_until * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" }) : null;
  return (
    <div data-testid="premium-shell" className="min-h-svh bg-[#07090e] text-slate-100">
      <header data-testid="premium-header" className="sticky top-0 z-30 border-b border-amber-400/20 bg-[#0b0d12]/92 px-4 py-3 backdrop-blur-xl sm:px-6">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-amber-300 text-[#1a1203]"><Activity className="size-5" /></div>
            <div>
              <p className="font-heading text-sm font-semibold tracking-wide text-white">EDGEDESK <span className="ml-1 rounded bg-amber-300 px-1.5 py-0.5 text-[10px] font-bold text-[#1a1203]">PREMIUM</span></p>
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Live indices · SENSEX · stocks · Kotak Neo data</p>
            </div>
          </div>
          {user.premium && (
            <nav aria-label="Premium sections" className="flex items-center gap-1 rounded-lg border border-[#202b42] bg-[#0e131d] p-1">
              {([["indices", "Indices & charts", "/premium"], ["stocks", "Stocks", "/premium/stocks"], ["alerts", "Alerts", "/premium/alerts"]] as const).map(([id, label, to]) => (
                <Link key={id} to={to} data-testid={`premium-tab-${id}`} aria-current={activeTab === id ? "page" : undefined} className={`rounded-md px-3.5 py-2 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200/60 ${activeTab === id ? "bg-amber-300 text-[#1a1203]" : "text-slate-400 hover:text-slate-200"}`}>{label}{id === "alerts" && unread > 0 && <span data-testid="alert-badge" className="ml-1.5 rounded-full bg-rose-500 px-1.5 text-[10px] font-bold text-white">{unread}</span>}</Link>
              ))}
            </nav>
          )}
          <div className="flex items-center gap-3 text-xs">
            {user.premium && until && <span data-testid="premium-until" className="hidden text-slate-500 sm:inline">Premium until {until}</span>}
            <Link to="/" data-testid="back-to-desk" className="rounded-md border border-[#26334b] px-3 py-1.5 text-slate-200 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">← Options desk</Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-4 py-5 pb-24 sm:px-6">
        {user.premium ? view === "indices" ? <PremiumIndices /> : view === "stocks" ? <PremiumStocks /> : view === "compare" ? <StockCompare /> : view === "alerts" ? <AlertsPage /> : <StockPage symbol={(symbol ?? "").toUpperCase()} /> : <Locked email={user.email} />}
        {user.premium && <p className="mt-6 border-t border-[#1e2638] pt-4 text-[11px] leading-relaxed text-slate-600">Live prices come only from your Kotak Neo feed during NSE/BSE hours (09:15–15:30 IST, Mon–Fri), and every page says whether its numbers are live, from the last session, delayed or unavailable. Intraday candles build up from live ticks; longer timeframes also use imported history when the owner has loaded it. Signals, setups and tested results are informational analysis of past prices, not investment advice or a promise, and can be wrong. No orders are placed from this page.</p>}
      </main>
    </div>
  );
}
