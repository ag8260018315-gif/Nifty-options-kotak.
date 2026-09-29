import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";

import { ApiError, apiGet, apiPost } from "@/lib/api";

interface Plan {
  trial_days: number;
  price_inr: number;
  period: string;
  payments_live: boolean;
  signups_open: boolean;
}

const INCLUDED = ["Real-time market analytics", "Option chain", "Greeks", "PCR and OI", "AI analysis", "CSV export", "NIFTY, BANKNIFTY, FINNIFTY"];

export default function Upgrade({ email, onSignOut, onApproved }: { email: string | null; onSignOut: () => void; onApproved: () => void }) {
  const planQuery = useQuery({ queryKey: ["public-plan"], queryFn: () => apiGet<Plan>("/public/plan"), retry: 1 });
  const price = `₹${planQuery.data?.price_inr ?? 189}`;
  const period = planQuery.data?.period ?? "month";
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestContinue = async () => {
    if (!email) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<{ status: "pending" | "approved" }>("/access/request", { email, name: null, note: "Asked to continue after the free trial." });
      if (result.status === "approved") onApproved();
      else setSent(true);
    } catch (caught) {
      const detail = caught instanceof ApiError ? (caught.body as { detail?: unknown } | null)?.detail : null;
      setError(typeof detail === "string" ? detail : "That didn't go through. Try again shortly.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="upgrade-page" className="flex min-h-screen items-center justify-center bg-[#070a11] px-5 py-12 text-[#e6ebf4]">
      <div className="w-full max-w-[560px]">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-[#e0314b] text-white"><Activity className="size-[18px]" /></span>
          <span className="font-heading text-[15px] font-semibold">NIFTY Options Desk</span>
        </div>
        <div className="mt-8 rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,rgba(255,255,255,0.045),rgba(255,255,255,0.01))] p-7 sm:p-9">
          <h1 className="font-heading text-[30px] font-bold leading-tight tracking-tight">Your free trial has ended</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-[#8c98ae]">Thanks for trying the desk. Keep the live chain, Greeks, PCR, AI analyst and exports for {price}/{period}.</p>
          <ul className="mt-6 grid gap-2.5 sm:grid-cols-2">
            {INCLUDED.map((item) => (
              <li key={item} className="flex items-center gap-2.5 text-[14.5px] text-[#d5dbe6]">
                <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0 text-emerald-300"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                {item}
              </li>
            ))}
          </ul>
          {sent ? (
            <p data-testid="upgrade-sent" role="status" className="mt-8 rounded-xl border border-emerald-400/25 bg-emerald-400/[0.07] px-4 py-3 text-[14px] leading-relaxed text-emerald-100">
              Request sent. We'll email {email} when your access continues. You can close this page.
            </p>
          ) : (
            <>
              <button type="button" data-testid="upgrade-continue" disabled={busy || !email} onClick={() => void requestContinue()} className="mt-8 h-12 w-full rounded-xl bg-[#e6ebf4] text-[15px] font-semibold text-[#070a11] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#070a11] disabled:opacity-50">
                {busy ? "Sending…" : `Continue with ${price}/${period}`}
              </button>
              <p className="mt-3 text-center text-[12.5px] leading-relaxed text-[#6b778d]">Online payment isn't live yet. This sends your request to the owner, and nothing is charged.</p>
            </>
          )}
          {error && <p role="alert" className="mt-4 rounded-lg border border-rose-400/30 bg-rose-400/[0.07] px-4 py-3 text-[13.5px] text-rose-100">{error}</p>}
        </div>
        <p className="mt-6 text-center text-[13px] text-[#6b778d]">
          Signed in as {email}.{" "}
          <button type="button" onClick={onSignOut} className="rounded text-[#c3cbda] underline underline-offset-4 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40">Sign out</button>
        </p>
      </div>
    </div>
  );
}
