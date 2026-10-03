import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Activity, Database, Gauge, Lock, ShieldCheck, Target } from "lucide-react";

import PremiumIndices from "@/components/premium/PremiumIndices";
import PremiumStocks from "@/components/premium/PremiumStocks";
import { apiPost } from "@/lib/api";

export interface PremiumUser {
  email: string | null;
  premium: boolean;
  premium_until?: number | null;
}

type Tab = "indices" | "stocks";

const FEATURES = [
  { icon: Gauge, title: "Advanced live charts", text: "SENSEX, NIFTY 50, BANK NIFTY and FIN NIFTY with interactive candlesticks, EMA, Bollinger bands, VWAP, RSI and MACD." },
  { icon: Database, title: "Live Indian stocks", text: "Large-cap NSE stocks with continuously updating prices, change, volume and a trend and signal for each." },
  { icon: Target, title: "Signals and setups", text: "Transparent buy/sell scoring, support and resistance, volume spikes, and a ranked list of potential buying setups." },
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
  const [tab, setTab] = useState<Tab>("indices");
  const until = user.premium_until ? new Date(user.premium_until * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" }) : null;
  return (
    <div data-testid="premium-shell" className="min-h-svh bg-[#07090e] text-slate-100">
      <header data-testid="premium-header" className="sticky top-0 z-30 border-b border-amber-400/20 bg-[#0b0d12]/92 px-4 py-3 backdrop-blur-xl sm:px-6">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-amber-300 text-[#1a1203]"><Activity className="size-5" /></div>
            <div>
              <p className="font-heading text-sm font-semibold tracking-wide text-white">NIFTY OPTIONS DESK <span className="ml-1 rounded bg-amber-300 px-1.5 py-0.5 text-[10px] font-bold text-[#1a1203]">PREMIUM</span></p>
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Live indices · SENSEX · stocks · Kotak Neo data</p>
            </div>
          </div>
          {user.premium && (
            <nav aria-label="Premium sections" className="flex items-center gap-1 rounded-lg border border-[#202b42] bg-[#0e131d] p-1">
              {([["indices", "Indices & charts"], ["stocks", "Stocks"]] as const).map(([id, label]) => (
                <button key={id} type="button" data-testid={`premium-tab-${id}`} aria-pressed={tab === id} onClick={() => setTab(id)} className={`rounded-md px-3.5 py-2 text-xs font-semibold ${tab === id ? "bg-amber-300 text-[#1a1203]" : "text-slate-400 hover:text-slate-200"}`}>{label}</button>
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
        {user.premium ? tab === "indices" ? <PremiumIndices /> : <PremiumStocks /> : <Locked email={user.email} />}
        {user.premium && <p className="mt-6 border-t border-[#1e2638] pt-4 text-[11px] leading-relaxed text-slate-600">Live prices and candles come only from your Kotak Neo feed during NSE/BSE hours (09:15–15:30 IST, Mon–Fri). Candles and indicators build up from live ticks, so a chart starts when the server starts receiving prices and there is no historical backfill. Signals and setups are informational analysis, not investment advice, and can be wrong. No orders are placed from this page.</p>}
      </main>
    </div>
  );
}
