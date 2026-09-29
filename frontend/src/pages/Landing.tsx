import { useEffect, useState } from "react";
import { Activity, LockKeyhole } from "lucide-react";

import { ApiError, apiPost } from "@/lib/api";

type Step = "email" | "code";

const FEATURES: { title: string; body: string }[] = [
  { title: "Live option chain", body: "ATM ±10 strikes for NIFTY, BANKNIFTY and FINNIFTY, calls and puts side by side, streamed from the Kotak Neo feed." },
  { title: "PCR and max pain", body: "Recalculated as ticks arrive, with open interest for every strike in the window." },
  { title: "Trade plan", body: "A signal only when PCR and 5- and 15-minute price momentum agree, with an index stop and a premium stop." },
  { title: "Candle charts", body: "1, 5 and 15 minute candles built from live index ticks, starting at the open." },
  { title: "Claude analyst", body: "Ask about the chain in plain language. It explains the setup, the stops and the risks." },
  { title: "Daily exports", body: "A CSV of each session's verified snapshots, ready for your own review." },
];

// Decorative only: relative bar lengths, no prices or market data.
const LADDER_CALLS = [18, 24, 31, 42, 55, 68, 49, 37, 27, 20, 14];
const LADDER_PUTS = [12, 19, 26, 35, 47, 72, 58, 44, 33, 25, 17];
const ATM_ROW = 5;

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

function SignInPanel({ onSignedIn }: { onSignedIn: () => void }) {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

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
      <div className="mb-8 flex size-11 items-center justify-center rounded-xl border border-[#1d283c] bg-[#131b2a] text-[#e6ebf4]">
        <LockKeyhole className="size-5" />
      </div>
      <h2 data-testid="signin-title" className="font-heading text-2xl font-semibold tracking-tight text-[#e6ebf4]">Sign in</h2>

      {step === "email" ? (
        <form
          data-testid="signin-email-form"
          className="mt-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && email.trim()) void sendCode();
          }}
        >
          <p className="text-[15px] leading-relaxed text-[#8c98ae]">Access is by invitation. Enter your approved email and we'll send you a 6-digit code.</p>
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
        </form>
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
              onClick={() => {
                setStep("email");
                setError(null);
              }}
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

      <p className="mt-10 text-[13px] leading-relaxed text-[#5f6c84]">No password to remember. Each code works once, and you stay signed in on this device for 7 days.</p>
    </div>
  );
}

export default function Landing({ onSignedIn }: { onSignedIn: () => void }) {
  return (
    <div data-testid="landing-page" className="min-h-screen bg-[#080c14] text-[#e6ebf4]">
      <div className="mx-auto grid min-h-screen max-w-[1400px] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(380px,440px)]">
        <header className="px-6 pt-8 sm:px-10 lg:col-start-1 lg:row-start-1 lg:px-14 lg:pt-12">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-[#e0314b] text-white">
              <Activity className="size-5" />
            </div>
            <span className="font-heading text-[15px] font-semibold tracking-tight">NIFTY Options Desk</span>
          </div>
          <h1 data-testid="landing-headline" className="mt-14 max-w-[15ch] font-heading text-[clamp(2.5rem,5.2vw,4.5rem)] font-bold leading-[1.02] tracking-[-0.03em]">
            Your option chain, live from Kotak Neo.
          </h1>
          <p className="mt-6 max-w-[56ch] text-[17px] leading-[1.65] text-[#a3adc0]">
            A private, read-only desk for NIFTY, BANKNIFTY and FINNIFTY. Watch the chain move, see where PCR and price agree, and ask Claude to explain the setup. It never places orders.
          </p>
          <div className="mt-12 lg:mt-16">
            <StrikeLadder />
          </div>
        </header>

        <aside className="border-y border-[#1d283c] bg-[#0e1420] px-6 py-12 sm:px-10 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:border-y-0 lg:border-l lg:py-0">
          <div className="flex items-start justify-center lg:sticky lg:top-0 lg:h-screen lg:items-center">
            <SignInPanel onSignedIn={onSignedIn} />
          </div>
        </aside>

        <section aria-label="What the desk does" className="px-6 pb-12 pt-14 sm:px-10 lg:col-start-1 lg:row-start-2 lg:px-14 lg:pb-14 lg:pt-20">
          <dl className="grid max-w-3xl grid-cols-1 gap-x-12 sm:grid-cols-2">
            {FEATURES.map((feature) => (
              <div key={feature.title} className="border-t border-[#1d283c] py-5">
                <dt className="font-heading text-[15px] font-semibold text-[#e6ebf4]">{feature.title}</dt>
                <dd className="mt-1.5 text-[14px] leading-relaxed text-[#8c98ae]">{feature.body}</dd>
              </div>
            ))}
          </dl>
          <p data-testid="landing-disclaimer" className="mt-10 max-w-3xl text-[12.5px] leading-relaxed text-[#5f6c84]">
            For information only, not investment advice. Signals follow a fixed rule and can be wrong; check price, liquidity and risk before any trade. Uses the Kotak Neo API and is not affiliated with or endorsed by Kotak Securities.
          </p>
        </section>
      </div>
    </div>
  );
}
