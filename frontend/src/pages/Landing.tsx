import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, LockKeyhole } from "lucide-react";

import { ApiError, apiGet, apiPost } from "@/lib/api";

type Step = "email" | "code" | "request" | "requested";
type IndexSymbol = "NIFTY" | "BANKNIFTY" | "FINNIFTY";

interface TickerItem {
  symbol: IndexSymbol;
  name: string;
  available: boolean;
  state: string;
  ltp: number | null;
  change: number | null;
  pct_change: number | null;
  prev_close: number | null;
  last_tick: string | null;
}

interface TickerResponse {
  items: TickerItem[];
  delay_minutes: number;
  refresh_seconds: number;
  generated_at: string;
}

interface ChartPoint {
  t: number;
  c: number;
}

interface ChartSeries {
  symbol: IndexSymbol;
  name: string;
  trading_day: string | null;
  is_today: boolean;
  points: ChartPoint[];
}

interface ChartsResponse {
  series: ChartSeries[];
  interval: string;
  delay_minutes: number;
  generated_at: string;
}

interface Plan {
  trial_days: number;
  price_inr: number;
  period: string;
  payments_live: boolean;
  signups_open: boolean;
}

const FALLBACK_PLAN: Plan = { trial_days: 7, price_inr: 189, period: "month", payments_live: false, signups_open: false };
const SYMBOLS: { symbol: IndexSymbol; name: string }[] = [
  { symbol: "NIFTY", name: "NIFTY 50" },
  { symbol: "BANKNIFTY", name: "BANKNIFTY" },
  { symbol: "FINNIFTY", name: "FINNIFTY" },
];

// Decorative only: relative bar lengths, no prices or market data.
const LADDER_CALLS = [18, 24, 31, 42, 55, 68, 49, 37, 27, 20, 14];
const LADDER_PUTS = [12, 19, 26, 35, 47, 72, 58, 44, 33, 25, 17];
const ATM_ROW = 5;

const FEATURES: { title: string; body: string }[] = [
  { title: "Live index data", body: "NIFTY 50, BANKNIFTY and FINNIFTY from the Kotak Neo feed while the market is open." },
  { title: "Option chain", body: "ATM ±10 strikes with calls and puts side by side, OI and change in OI, and the ATM strike marked." },
  { title: "Greeks", body: "IV, delta, gamma, theta and vega for every strike, estimated from live option prices." },
  { title: "PCR", body: "Put-call ratio for the strikes on screen, with how it has moved since the day's first update." },
  { title: "OI analytics", body: "Max pain, OI build-up and the strikes carrying the heaviest call and put positioning." },
  { title: "AI market analyst", body: "Ask Claude about the chain. It explains what the data shows, what it may mean, and the risks." },
  { title: "CSV export", body: "Download each session's verified snapshots for your own review and records." },
  { title: "Three indices", body: "Switch between NIFTY, BANKNIFTY and FINNIFTY without reloading the page." },
];

const GREEK_NOTES: { name: string; note: string }[] = [
  { name: "Delta", note: "How much an option's price may change for a one-point move in the index, all else equal." },
  { name: "Gamma", note: "How quickly delta changes as the index moves." },
  { name: "Theta", note: "The estimated time decay of an option, per day." },
  { name: "Vega", note: "How much the price may change for a one-point change in implied volatility." },
  { name: "IV", note: "The volatility level implied by the option's own price." },
];

const AI_QUESTIONS = [
  "What is happening around the ATM strike?",
  "Where is the strongest OI concentration?",
  "Explain today's PCR.",
  "Summarize the current market structure.",
];

const FAQ: { q: string; a: string }[] = [
  { q: "Is the market data live?", a: "Index prices and the option chain come from the Kotak Neo market feed while NSE is open, 09:15 to 15:30 IST on trading days. Outside those hours you see the latest available data, clearly labelled as closed." },
  { q: "Where does the data come from?", a: "From the Kotak Neo API. The desk is independent and is not affiliated with or endorsed by Kotak Securities." },
  { q: "Are the Greeks exact?", a: "No. IV, delta, gamma, theta and vega are estimates from a Black-Scholes model using live option prices. Treat them as a guide, not as exchange figures." },
  { q: "What does the AI analyst do?", a: "Claude reads the same data shown on your dashboard and explains it in plain language. It separates what the data shows from its interpretation, and it can be wrong." },
  { q: "What happens after the free trial?", a: "Access pauses and you can ask to continue from the same screen. Online payment isn't live yet, so nothing is charged." },
  { q: "Does it place trades?", a: "No. The desk is read-only. It never places, changes or cancels orders." },
  { q: "Is this investment advice?", a: "No. It's an information tool. Indicators are calculated by fixed formulas and can be misleading, so check price, liquidity and risk yourself." },
];

const priceFormat = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function formatPrice(value: number) {
  return priceFormat.format(value);
}

function istTime(value: string | number | null, withSeconds = false) {
  if (value === null) return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: withSeconds ? "2-digit" : undefined, hour12: false, timeZone: "Asia/Kolkata" });
}

function sessionLabel(day: string | null) {
  if (!day) return "";
  const date = new Date(`${day}T00:00:00+05:30`);
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

// Smoothly moves a displayed number to its new real value (no invented intermediate data is stored).
function useTweenedNumber(target: number | null, reduced: boolean): number | null {
  const [value, setValue] = useState<number | null>(target);
  const current = useRef<number | null>(target);
  useEffect(() => {
    const from = current.current;
    if (target === null || from === null || reduced || from === target) {
      current.current = target;
      setValue(target);
      return;
    }
    const started = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / 650);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = progress >= 1 ? target : from + (target - from) * eased;
      current.current = next;
      setValue(next);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, reduced]);
  return value;
}

function useChangeTint(value: number | null) {
  const previous = useRef<number | null>(value);
  const [tint, setTint] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (value === null || before === null || value === before) return;
    setTint(value > before ? "up" : "down");
    const timer = window.setTimeout(() => setTint(null), 900);
    return () => window.clearTimeout(timer);
  }, [value]);
  return tint;
}

function focusSignIn(reduced: boolean) {
  const field = document.getElementById("signin-email") ?? document.getElementById("request-email") ?? document.getElementById("signin-code");
  const panel = document.getElementById("get-started");
  (panel ?? field)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
  field?.focus({ preventScroll: true });
}

function StatePill({ state, delayMinutes }: { state: string; delayMinutes: number }) {
  if (state === "LIVE") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/[0.08] px-2 py-0.5 text-[11px] font-medium text-emerald-300">
        <span className="relative flex size-1.5">
          <span className="absolute inline-flex size-full rounded-full bg-emerald-300 opacity-70 motion-safe:animate-ping" />
          <span className="relative inline-flex size-1.5 rounded-full bg-emerald-300" />
        </span>
        {delayMinutes > 0 ? `Live, ${delayMinutes} min delayed` : "Live"}
      </span>
    );
  }
  const label = state === "MARKET_CLOSED" ? "Market closed" : state === "STALE" ? "Delayed" : "Unavailable";
  const tone = state === "STALE" ? "border-amber-400/25 bg-amber-400/[0.08] text-amber-300" : "border-white/10 bg-white/[0.04] text-[#9aa5b8]";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${tone}`}>{label}</span>;
}

function IndexChart({ symbol, series, ltp, live, up, reduced }: { symbol: IndexSymbol; series: ChartSeries | undefined; ltp: number | null; live: boolean; up: boolean; reduced: boolean }) {
  const points = useMemo(() => {
    const base = series?.points ?? [];
    const last = base[base.length - 1];
    if (!series?.is_today || !live || ltp === null || !last) return base;
    const now = Math.floor(Date.now() / 1000);
    return [...base, { t: Math.max(last.t + 1, now), c: ltp }];
  }, [series, ltp, live]);

  if (points.length < 2) {
    return (
      <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-white/[0.08] px-4 text-center text-[12px] leading-relaxed text-[#6b778d]">
        {series && series.points.length === 0 ? "The chart builds from 09:15 IST as live index ticks arrive." : "Chart data unavailable."}
      </div>
    );
  }
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return null;
  const closes = points.map((point) => point.c);
  const high = Math.max(...closes);
  const low = Math.min(...closes);
  const span = high - low || Math.max(1, high * 0.0005);
  const width = 300;
  const height = 100;
  const x = (t: number) => ((t - first.t) / Math.max(1, last.t - first.t)) * width;
  const y = (c: number) => 6 + ((high - c) / span) * (height - 12);
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(point.t).toFixed(2)},${y(point.c).toFixed(2)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const color = up ? "#34d399" : "#fb7185";
  const gradientId = `nod-fill-${symbol}`;
  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-28 w-full overflow-visible" role="img" aria-label={`${symbol} one-minute price line, ${istTime(first.t)} to ${istTime(last.t)} IST`}>
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.22" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradientId})`} className={reduced ? "" : "nod-fade"} />
        <path d={line} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength={1} className={reduced ? "" : "nod-draw"} />
      </svg>
      <div className="mt-1.5 flex justify-between font-mono text-[10px] text-[#5f6c84]">
        <span>{istTime(first.t)}</span>
        <span>
          High {formatPrice(high)}&nbsp;&nbsp;Low {formatPrice(low)}
        </span>
        <span>{istTime(last.t)}</span>
      </div>
    </div>
  );
}

function MarketCard({ symbol, name, item, series, delayMinutes, reduced, index }: { symbol: IndexSymbol; name: string; item: TickerItem | undefined; series: ChartSeries | undefined; delayMinutes: number; reduced: boolean; index: number }) {
  const ltp = item?.available ? item.ltp : null;
  const shown = useTweenedNumber(ltp, reduced);
  const tint = useChangeTint(ltp);
  const change = item?.available ? item.change : null;
  const pct = item?.available ? item.pct_change : null;
  const up = (change ?? 0) >= 0;
  const state = item?.state ?? "UNAVAILABLE";
  const priceTone = tint === "up" ? "text-emerald-300" : tint === "down" ? "text-rose-300" : "text-[#eef2f8]";
  const lastSession = series && series.trading_day && !series.is_today ? sessionLabel(series.trading_day) : null;
  return (
    <article
      data-testid={`market-card-${symbol}`}
      className={`rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5 backdrop-blur-sm ${reduced ? "" : "nod-rise"}`}
      style={reduced ? undefined : { animationDelay: `${120 + index * 90}ms` }}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-[15px] font-semibold text-[#e6ebf4]">{name}</h3>
        <StatePill state={state} delayMinutes={delayMinutes} />
      </div>
      {ltp === null || shown === null ? (
        <div className="mt-4">
          <p className="font-heading text-[28px] font-semibold leading-none text-[#5f6c84]">—</p>
          <p className="mt-2 text-[13px] text-[#8c98ae]">Market data unavailable</p>
        </div>
      ) : (
        <div className="mt-4">
          <p data-testid={`market-price-${symbol}`} className={`font-heading text-[28px] font-semibold leading-none tabular-nums tracking-tight transition-colors duration-700 ${priceTone}`}>{formatPrice(shown)}</p>
          <p className={`mt-2 text-[13px] font-medium tabular-nums ${up ? "text-emerald-300" : "text-rose-300"}`}>
            {change === null ? "Change unavailable" : `${up ? "▲" : "▼"} ${up ? "+" : ""}${formatPrice(change)}${pct === null ? "" : ` (${up ? "+" : ""}${pct.toFixed(2)}%)`}`}
          </p>
        </div>
      )}
      <div className="mt-5">
        <IndexChart symbol={symbol} series={series} ltp={ltp} live={state === "LIVE"} up={up} reduced={reduced} />
      </div>
      <p className="mt-3 text-[11px] text-[#6b778d]">
        {state === "MARKET_CLOSED" ? "Latest available data. " : ""}
        {lastSession ? `Chart: last session, ${lastSession}. ` : ""}
        Updated {istTime(item?.last_tick ?? null, true)} IST
      </p>
    </article>
  );
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (error.status === 422) return "Check the email or code and try again.";
    if (error.status >= 500) return "The server couldn't complete that. Try again shortly.";
  }
  return "Can't reach the server. Check your connection and try again.";
}

function StrikeLadder() {
  return (
    <div aria-hidden="true" className="w-full max-w-xl select-none">
      <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-end text-[13px] text-[#8c98ae]">
        <span className="text-left text-[#34d399]">Calls</span>
        <span className="px-4">Strike</span>
        <span className="text-right text-[#fb7185]">Puts</span>
      </div>
      <div className="space-y-[5px]">
        {LADDER_CALLS.map((callWidth, row) => {
          const atm = row === ATM_ROW;
          return (
            <div key={row} className="relative grid grid-cols-[1fr_28px_1fr] items-center">
              <div className="flex justify-end">
                <div className={`h-[9px] rounded-l-sm ${atm ? "bg-[#34d399]" : "bg-[#34d399]/35"}`} style={{ width: `${callWidth}%` }} />
              </div>
              <div className="flex justify-center">
                {atm ? (
                  <span className="relative flex size-2.5">
                    <span className="absolute inline-flex size-full rounded-full bg-[#e6ebf4] opacity-60 motion-safe:animate-ping" />
                    <span className="relative inline-flex size-2.5 rounded-full bg-[#e6ebf4]" />
                  </span>
                ) : (
                  <span className="h-[9px] w-px bg-[#1d283c]" />
                )}
              </div>
              <div className="flex justify-start">
                <div className={`h-[9px] rounded-r-sm ${atm ? "bg-[#fb7185]" : "bg-[#fb7185]/35"}`} style={{ width: `${LADDER_PUTS[row]}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SignInPanel({ onSignedIn, signupsOpen, trialDays }: { onSignedIn: () => void; signupsOpen: boolean; trialDays: number }) {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [info, setInfo] = useState<string | null>(null);

  const goTo = (next: Step) => {
    setStep(next);
    setError(null);
    setInfo(null);
  };

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const sendCode = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiPost("/access/request-code", { email: email.trim() });
      setStep("code");
      setCode("");
      setCooldown(60);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 403) {
        goTo("request");
        setInfo("This email doesn't have access yet. Send a request and you'll get an email once it's approved.");
      } else {
        setError(errorText(caught));
      }
    } finally {
      setBusy(false);
    }
  };

  const requestAccess = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<{ status: "pending" | "approved" }>("/access/request", { email: email.trim(), name: name.trim() || null, note: note.trim() || null });
      if (result.status === "approved") {
        goTo("email");
        setInfo("This email already has access. Send yourself a code to sign in.");
      } else {
        goTo("requested");
      }
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiPost("/access/verify", { email: email.trim(), code });
      onSignedIn();
    } catch (caught) {
      setError(errorText(caught));
      setBusy(false);
    }
  };

  const codeReady = code.replace(/\D/g, "").length === 6;

  return (
    <div className="w-full max-w-sm">
      <div className="mb-6 flex size-10 items-center justify-center rounded-xl border border-[#1d283c] bg-[#131b2a] text-[#e6ebf4]">
        <LockKeyhole className="size-[18px]" />
      </div>
      <h2 data-testid="signin-title" className="font-heading text-2xl font-semibold tracking-tight text-[#e6ebf4]">
        {step === "request" || step === "requested" ? "Request access" : step === "code" ? "Check your email" : signupsOpen ? `Start your ${trialDays}-day free trial` : "Sign in"}
      </h2>

      {info && (
        <p data-testid="signin-info" className="mt-3 rounded-lg border border-[#26334b] bg-[#131b2a] px-4 py-3 text-sm leading-relaxed text-[#c3cbda]">{info}</p>
      )}

      {step === "email" ? (
        <form
          data-testid="signin-email-form"
          className="mt-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && email.trim()) void sendCode();
          }}
        >
          <p className="text-[15px] leading-relaxed text-[#8c98ae]">
            {signupsOpen ? `Enter your email and we'll send a 6-digit code. New here? Your ${trialDays}-day trial starts when you confirm it. Already a member? The same code signs you in.` : "Enter your email. If it has access, we'll send you a 6-digit code."}
          </p>
          <label htmlFor="signin-email" className="mt-8 block text-sm text-[#c3cbda]">Email</label>
          <input
            id="signin-email"
            data-testid="signin-email-input"
            type="email"
            autoComplete="email"
            inputMode="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            className="mt-2 h-12 w-full rounded-lg border border-[#26334b] bg-[#0a0f19] px-4 text-[15px] text-[#e6ebf4] placeholder:text-[#4d5a72] outline-none transition-colors focus-visible:border-[#8c98ae] focus-visible:ring-2 focus-visible:ring-[#8c98ae]/30"
          />
          <button
            type="submit"
            data-testid="signin-send-code"
            disabled={busy || !email.trim()}
            className="mt-4 h-12 w-full rounded-lg bg-[#e6ebf4] text-[15px] font-semibold text-[#080c14] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e6ebf4]/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e1420] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Sending code…" : "Send code"}
          </button>
          {!signupsOpen && (
            <p className="mt-6 text-sm text-[#8c98ae]">
              New here?{" "}
              <button type="button" data-testid="signin-go-request" onClick={() => goTo("request")} className="rounded text-[#e6ebf4] underline underline-offset-4 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8c98ae]/40">
                Request access
              </button>
            </p>
          )}
        </form>
      ) : step === "request" ? (
        <form
          data-testid="request-access-form"
          className="mt-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && email.trim()) void requestAccess();
          }}
        >
          {!info && <p className="text-[15px] leading-relaxed text-[#8c98ae]">The owner reviews every request. You'll get an email when yours is approved.</p>}
          <label htmlFor="request-email" className="mt-8 block text-sm text-[#c3cbda]">Email</label>
          <input id="request-email" data-testid="request-email-input" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" className="mt-2 h-12 w-full rounded-lg border border-[#26334b] bg-[#0a0f19] px-4 text-[15px] text-[#e6ebf4] placeholder:text-[#4d5a72] outline-none transition-colors focus-visible:border-[#8c98ae] focus-visible:ring-2 focus-visible:ring-[#8c98ae]/30" />
          <label htmlFor="request-name" className="mt-5 block text-sm text-[#c3cbda]">Name <span className="text-[#5f6c84]">(optional)</span></label>
          <input id="request-name" data-testid="request-name-input" type="text" autoComplete="name" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} className="mt-2 h-12 w-full rounded-lg border border-[#26334b] bg-[#0a0f19] px-4 text-[15px] text-[#e6ebf4] placeholder:text-[#4d5a72] outline-none transition-colors focus-visible:border-[#8c98ae] focus-visible:ring-2 focus-visible:ring-[#8c98ae]/30" />
          <label htmlFor="request-note" className="mt-5 block text-sm text-[#c3cbda]">How will you use it? <span className="text-[#5f6c84]">(optional)</span></label>
          <textarea id="request-note" data-testid="request-note-input" maxLength={300} rows={3} value={note} onChange={(event) => setNote(event.target.value)} className="mt-2 w-full resize-none rounded-lg border border-[#26334b] bg-[#0a0f19] px-4 py-3 text-[15px] text-[#e6ebf4] outline-none transition-colors focus-visible:border-[#8c98ae] focus-visible:ring-2 focus-visible:ring-[#8c98ae]/30" />
          <button type="submit" data-testid="request-access-submit" disabled={busy || !email.trim()} className="mt-4 h-12 w-full rounded-lg bg-[#e6ebf4] text-[15px] font-semibold text-[#080c14] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e6ebf4]/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e1420] disabled:cursor-not-allowed disabled:opacity-40">
            {busy ? "Sending request…" : "Request access"}
          </button>
          <p className="mt-6 text-sm text-[#8c98ae]">
            Already approved?{" "}
            <button type="button" data-testid="request-go-signin" onClick={() => goTo("email")} className="rounded text-[#e6ebf4] underline underline-offset-4 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8c98ae]/40">
              Sign in
            </button>
          </p>
        </form>
      ) : step === "requested" ? (
        <div data-testid="request-access-sent" className="mt-3">
          <p className="text-[15px] leading-relaxed text-[#8c98ae]">
            Request sent for <span className="text-[#e6ebf4]">{email.trim()}</span>. You'll get an email when the owner approves it. Then come back here and sign in with a code.
          </p>
          <button type="button" data-testid="request-done-signin" onClick={() => goTo("email")} className="mt-8 h-12 w-full rounded-lg border border-[#26334b] text-[15px] font-semibold text-[#e6ebf4] hover:bg-[#131b2a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8c98ae]/40">
            Back to sign in
          </button>
        </div>
      ) : (
        <form
          data-testid="signin-code-form"
          className="mt-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && codeReady) void verify();
          }}
        >
          <p className="text-[15px] leading-relaxed text-[#8c98ae]">
            We sent a code to <span className="text-[#e6ebf4]">{email.trim()}</span>. It expires in 10 minutes.
          </p>
          <label htmlFor="signin-code" className="mt-8 block text-sm text-[#c3cbda]">6-digit code</label>
          <input
            id="signin-code"
            data-testid="signin-code-input"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={7}
            autoFocus
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/[^\d ]/g, ""))}
            placeholder="000000"
            className="mt-2 h-14 w-full rounded-lg border border-[#26334b] bg-[#0a0f19] px-4 text-center font-mono text-2xl tracking-[0.5em] text-[#e6ebf4] placeholder:text-[#2c3850] outline-none transition-colors focus-visible:border-[#8c98ae] focus-visible:ring-2 focus-visible:ring-[#8c98ae]/30"
          />
          <button
            type="submit"
            data-testid="signin-verify"
            disabled={busy || !codeReady}
            className="mt-4 h-12 w-full rounded-lg bg-[#e6ebf4] text-[15px] font-semibold text-[#080c14] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e6ebf4]/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e1420] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <div className="mt-5 flex items-center justify-between text-sm">
            <button
              type="button"
              data-testid="signin-change-email"
              onClick={() => goTo("email")}
              className="rounded text-[#8c98ae] underline-offset-4 hover:text-[#e6ebf4] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8c98ae]/40"
            >
              Use a different email
            </button>
            <button
              type="button"
              data-testid="signin-resend"
              disabled={busy || cooldown > 0}
              onClick={() => void sendCode()}
              className="rounded text-[#8c98ae] underline-offset-4 hover:text-[#e6ebf4] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8c98ae]/40 disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
            >
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
            </button>
          </div>
        </form>
      )}

      {error && (
        <p data-testid="signin-error" role="alert" className="mt-5 rounded-lg border border-[#fb7185]/30 bg-[#fb7185]/[0.07] px-4 py-3 text-sm leading-relaxed text-[#fecdd3]">
          {error}
        </p>
      )}

      <p className="mt-8 text-[13px] leading-relaxed text-[#5f6c84]">
        {signupsOpen ? "No password and no card. Each code works once, and you stay signed in on this device for 7 days." : "No password to remember. Each code works once, and you stay signed in on this device for 7 days. The owner approves every account."}
      </p>
    </div>
  );
}

const KEYFRAMES = `
@keyframes nod-draw { from { stroke-dasharray: 1; stroke-dashoffset: 1; } to { stroke-dasharray: 1; stroke-dashoffset: 0; } }
@keyframes nod-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes nod-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.nod-draw { animation: nod-draw 1.6s cubic-bezier(.22,.8,.3,1) both; }
.nod-fade { animation: nod-fade 1.2s ease-out .5s both; }
.nod-rise { animation: nod-rise .7s cubic-bezier(.22,.8,.3,1) both; }
@media (prefers-reduced-motion: reduce) { .nod-draw, .nod-fade, .nod-rise { animation: none !important; } }
`;

const fetchTicker = () => apiGet<TickerResponse>("/public/ticker");
const fetchCharts = () => apiGet<ChartsResponse>("/public/charts");
const fetchPlan = () => apiGet<Plan>("/public/plan");

function marketSummary(items: TickerItem[]) {
  if (items.some((item) => item.state === "LIVE")) return { label: "Market open", tone: "text-emerald-300" };
  if (items.some((item) => item.state === "STALE")) return { label: "Market open, feed delayed", tone: "text-amber-300" };
  if (items.some((item) => item.state === "MARKET_CLOSED")) return { label: "Market closed", tone: "text-[#9aa5b8]" };
  return { label: "Market data unavailable", tone: "text-[#9aa5b8]" };
}

export default function Landing({ onSignedIn }: { onSignedIn: () => void }) {
  const reduced = usePrefersReducedMotion();
  const ticker = useQuery({ queryKey: ["public-ticker"], queryFn: fetchTicker, refetchInterval: 2000, retry: 1 });
  const charts = useQuery({ queryKey: ["public-charts"], queryFn: fetchCharts, refetchInterval: 15_000, retry: 1 });
  const planQuery = useQuery({ queryKey: ["public-plan"], queryFn: fetchPlan, retry: 1 });
  const plan = planQuery.data ?? FALLBACK_PLAN;
  const items = ticker.data?.items ?? [];
  const delay = ticker.data?.delay_minutes ?? 0;
  const summary = ticker.isError ? { label: "Market data unavailable", tone: "text-[#9aa5b8]" } : marketSummary(items);
  const lastUpdate = items.map((item) => item.last_tick).filter((value): value is string => Boolean(value)).sort().pop() ?? null;
  const price = `₹${plan.price_inr}`;
  const trialCta = plan.signups_open ? `Start ${plan.trial_days}-Day Free Trial` : "Sign in";

  return (
    <div data-testid="landing-page" className="relative isolate min-h-screen overflow-x-hidden bg-[#070a11] text-[#e6ebf4]">
      <style>{KEYFRAMES}</style>
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-[640px] bg-[radial-gradient(60%_60%_at_30%_0%,rgba(52,211,153,0.08),transparent_70%),radial-gradient(40%_50%_at_85%_10%,rgba(251,113,133,0.06),transparent_70%)]" />

      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#070a11]/80 backdrop-blur-md">
        <nav aria-label="Main" className="mx-auto flex h-16 max-w-[1280px] items-center justify-between gap-4 px-5 sm:px-8">
          <a href="#top" className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40">
            <span className="flex size-8 items-center justify-center rounded-lg bg-[#e0314b] text-white"><Activity className="size-[18px]" /></span>
            <span className="font-heading text-[15px] font-semibold tracking-tight">NIFTY Options Desk</span>
          </a>
          <div className="hidden items-center gap-7 text-[14px] text-[#9aa5b8] md:flex">
            <a href="#markets" className="hover:text-white">Markets</a>
            <a href="#features" className="hover:text-white">Features</a>
            <a href="#pricing" className="hover:text-white">Pricing</a>
            <a href="#faq" className="hover:text-white">FAQ</a>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => focusSignIn(reduced)} className="hidden h-9 rounded-lg px-3 text-[14px] text-[#c3cbda] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40 sm:block">Sign in</button>
            {plan.signups_open && (
              <button type="button" data-testid="nav-trial-cta" onClick={() => focusSignIn(reduced)} className="h-9 rounded-lg bg-[#e6ebf4] px-3.5 text-[13px] font-semibold text-[#070a11] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60">{trialCta}</button>
            )}
          </div>
        </nav>
      </header>

      <main id="top" className="relative">
        <section className="mx-auto grid max-w-[1280px] gap-12 px-5 pb-16 pt-14 sm:px-8 lg:grid-cols-[minmax(0,1fr)_420px] lg:gap-16 lg:pt-20">
          <div className={reduced ? "" : "nod-rise"}>
            <p className="inline-flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1 text-[12.5px] text-[#aeb8c9]">
              <span className="size-1.5 rounded-full bg-emerald-300" />
              Live market intelligence • NIFTY • BANKNIFTY • FINNIFTY
            </p>
            <h1 data-testid="landing-headline" className="mt-7 max-w-[14ch] font-heading text-[clamp(2.6rem,5.6vw,4.9rem)] font-bold leading-[1.02] tracking-[-0.035em]">
              See the Options Market Differently.
            </h1>
            <p className="mt-6 max-w-[58ch] text-[17px] leading-[1.65] text-[#a3adc0]">
              Real-time NIFTY options intelligence, Greeks, PCR, OI analytics and AI-powered market analysis in one professional dashboard. Read-only: it never places orders.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <button type="button" data-testid="hero-trial-cta" onClick={() => focusSignIn(reduced)} className="h-12 rounded-xl bg-[#e6ebf4] px-6 text-[15px] font-semibold text-[#070a11] shadow-[0_8px_30px_rgba(230,235,244,0.12)] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#070a11]">{trialCta}</button>
              <a href="#markets" className="flex h-12 items-center rounded-xl border border-white/[0.12] px-6 text-[15px] font-medium text-[#e6ebf4] hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40">View live markets</a>
            </div>
            {plan.signups_open && (
              <p data-testid="hero-price-line" className="mt-5 text-[14px] text-[#8c98ae]">
                <span className="font-semibold text-[#e6ebf4]">{plan.trial_days} days free.</span> Then {price}/{plan.period}. No card needed to start.
              </p>
            )}
          </div>

          <aside id="get-started" aria-label="Sign in" className="rounded-2xl border border-white/[0.08] bg-[#0c111b]/90 p-7 shadow-[0_20px_60px_rgba(0,0,0,0.45)] backdrop-blur sm:p-8">
            {plan.signups_open && (
              <p className="mb-5 inline-flex items-center rounded-full border border-emerald-400/25 bg-emerald-400/[0.08] px-2.5 py-1 text-[12px] font-semibold text-emerald-300">{plan.trial_days} days free, then {price}/{plan.period}</p>
            )}
            <SignInPanel onSignedIn={onSignedIn} signupsOpen={plan.signups_open} trialDays={plan.trial_days} />
          </aside>
        </section>

        <section id="markets" aria-labelledby="markets-title" className="mx-auto max-w-[1280px] scroll-mt-20 px-5 pb-20 sm:px-8">
          <div className="flex flex-col gap-3 border-t border-white/[0.06] pt-10 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="markets-title" className="font-heading text-[26px] font-semibold tracking-tight">Live markets</h2>
              <p className="mt-1.5 text-[14px] text-[#8c98ae]">Index prices from the Kotak Neo feed. Option chains, Greeks and analytics are inside the desk.</p>
            </div>
            <dl data-testid="market-status-meta" className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
              <div className="flex gap-1.5"><dt className="text-[#6b778d]">Status</dt><dd className={summary.tone}>{summary.label}</dd></div>
              <div className="flex gap-1.5"><dt className="text-[#6b778d]">Refresh</dt><dd className="text-[#c3cbda]">every {ticker.data?.refresh_seconds ?? 2} s{delay > 0 ? `, ${delay} min delayed` : ""}</dd></div>
              <div className="flex gap-1.5"><dt className="text-[#6b778d]">Last update</dt><dd className="tabular-nums text-[#c3cbda]">{istTime(lastUpdate, true)} IST</dd></div>
            </dl>
          </div>
          <div className="mt-7 grid gap-4 md:grid-cols-3">
            {SYMBOLS.map(({ symbol, name }, index) => (
              <MarketCard
                key={symbol}
                symbol={symbol}
                name={name}
                index={index}
                item={items.find((item) => item.symbol === symbol)}
                series={charts.data?.series.find((series) => series.symbol === symbol)}
                delayMinutes={delay}
                reduced={reduced}
              />
            ))}
          </div>
        </section>

        <section id="features" aria-labelledby="features-title" className="mx-auto max-w-[1280px] scroll-mt-20 px-5 pb-20 sm:px-8">
          <h2 id="features-title" className="max-w-[20ch] font-heading text-[clamp(1.8rem,3.2vw,2.5rem)] font-semibold leading-tight tracking-tight">Everything you need to read the options market</h2>
          <dl className="mt-9 grid gap-px overflow-hidden rounded-2xl border border-white/[0.07] bg-white/[0.07] sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((feature) => (
              <div key={feature.title} className="bg-[#0a0e17] p-6 transition-colors hover:bg-[#0d1320]">
                <dt className="font-heading text-[15px] font-semibold">{feature.title}</dt>
                <dd className="mt-2 text-[14px] leading-relaxed text-[#8c98ae]">{feature.body}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby="inside-title" className="mx-auto max-w-[1280px] px-5 pb-20 sm:px-8">
          <h2 id="inside-title" className="font-heading text-[clamp(1.8rem,3.2vw,2.5rem)] font-semibold tracking-tight">Inside the desk</h2>
          <p className="mt-2 max-w-[62ch] text-[15px] leading-relaxed text-[#8c98ae]">A preview of the working screens. Live values appear once you sign in.</p>
          <div className="mt-9 grid gap-4 lg:grid-cols-3">
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-6">
              <h3 className="font-heading text-[16px] font-semibold">Option chain</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-[#8c98ae]">Calls on the left, puts on the right, with the ATM strike marked and OI shaped around it.</p>
              <div className="mt-6"><StrikeLadder /></div>
            </div>
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-6">
              <h3 className="font-heading text-[16px] font-semibold">Greeks ladder</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-[#8c98ae]">Estimated from live option prices for every strike in the window.</p>
              <dl className="mt-5 divide-y divide-white/[0.06]">
                {GREEK_NOTES.map((greek) => (
                  <div key={greek.name} className="grid grid-cols-[64px_1fr] gap-3 py-2.5">
                    <dt className="font-heading text-[14px] font-semibold text-[#e6ebf4]">{greek.name}</dt>
                    <dd className="text-[13px] leading-relaxed text-[#8c98ae]">{greek.note}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-6">
              <h3 className="font-heading text-[16px] font-semibold">AI market analyst</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-[#8c98ae]">Claude analyzes the live market data in your dashboard and keeps what the data shows apart from its interpretation.</p>
              <ul className="mt-5 space-y-2">
                {AI_QUESTIONS.map((question) => (
                  <li key={question} className="w-fit max-w-full rounded-2xl rounded-bl-md border border-white/[0.08] bg-white/[0.04] px-3.5 py-2 text-[13.5px] text-[#d5dbe6]">{question}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section id="pricing" aria-labelledby="pricing-title" className="mx-auto max-w-[1280px] scroll-mt-20 px-5 pb-20 sm:px-8">
          <div className="grid items-center gap-10 rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,rgba(255,255,255,0.04),rgba(255,255,255,0.01))] p-7 sm:p-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div>
              <h2 id="pricing-title" className="font-heading text-[clamp(2rem,4vw,3rem)] font-bold leading-tight tracking-tight">
                {plan.trial_days} days free.<br />Then {price}/{plan.period}.
              </h2>
              <p className="mt-4 max-w-[46ch] text-[15px] leading-relaxed text-[#8c98ae]">
                One plan with everything included. No card needed to start. Online payment isn't live yet, so nothing is charged. When the trial ends you can ask to continue.
              </p>
              <button type="button" data-testid="pricing-trial-cta" onClick={() => focusSignIn(reduced)} className="mt-7 h-12 rounded-xl bg-[#e6ebf4] px-6 text-[15px] font-semibold text-[#070a11] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#070a11]">
                {plan.signups_open ? trialCta : "Request access"}
              </button>
            </div>
            <ul className="grid gap-3 sm:grid-cols-2">
              {[`${plan.trial_days}-day free trial`, "Real-time market analytics", "Option chain", "Greeks", "PCR and OI", "AI analysis", "CSV export", "NIFTY, BANKNIFTY, FINNIFTY"].map((item) => (
                <li key={item} className="flex items-center gap-2.5 text-[15px] text-[#d5dbe6]">
                  <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0 text-emerald-300"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="faq" aria-labelledby="faq-title" className="mx-auto max-w-[860px] scroll-mt-20 px-5 pb-20 sm:px-8">
          <h2 id="faq-title" className="font-heading text-[clamp(1.8rem,3.2vw,2.5rem)] font-semibold tracking-tight">Questions</h2>
          <div className="mt-7 divide-y divide-white/[0.07] border-y border-white/[0.07]">
            {FAQ.map((item) => (
              <details key={item.q} className="group py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded text-[16px] font-medium text-[#e6ebf4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40">
                  {item.q}
                  <span aria-hidden="true" className="text-[#6b778d] transition-transform group-open:rotate-45">+</span>
                </summary>
                <p className="mt-3 max-w-[70ch] text-[14.5px] leading-relaxed text-[#8c98ae]">{item.a}</p>
              </details>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-white/[0.06]">
        <div className="mx-auto flex max-w-[1280px] flex-col gap-4 px-5 py-8 text-[12.5px] leading-relaxed text-[#5f6c84] sm:px-8 md:flex-row md:items-start md:justify-between">
          <p className="max-w-[80ch]">
            For information only, not investment advice. Indicators are calculated by fixed formulas and can be misleading; check price, liquidity and risk before any trade. Greeks are model estimates. Uses the Kotak Neo API and is not affiliated with or endorsed by Kotak Securities.
          </p>
          <p className="shrink-0">NIFTY Options Desk</p>
        </div>
      </footer>
    </div>
  );
}
