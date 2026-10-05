import { useState } from "react";
import { Link } from "react-router-dom";
import { Activity } from "lucide-react";

import CheckoutDialog from "@/components/billing/CheckoutDialog";
import { Comparison, PlanCards } from "@/components/billing/Plans";
import { dateText, inr, useBilling, useBillingActions, type Billing } from "@/lib/billing";
import { explain } from "@/lib/exchange";

const TONE = { info: "border-sky-400/25 bg-sky-400/[0.07] text-sky-100", warn: "border-amber-300/30 bg-amber-300/[0.08] text-amber-100", error: "border-rose-400/30 bg-rose-400/[0.08] text-rose-100" };

function Current({ b }: { b: Billing }) {
  const { cancel, resume } = useBillingActions();
  const name = b.plan === "premium" ? "Premium" : "Standard";
  const price = b.plan === "premium" ? 399 : 189;
  return (
    <section data-testid="current-plan" aria-label="Your plan" className="rounded-2xl border border-white/[0.1] bg-white/[0.03] p-5">
      <p className="text-[12px] uppercase tracking-wider text-[#8c98ae]">Your plan</p>
      {b.status === "none" && b.premium_by_owner && <p className="mt-1 text-lg font-semibold text-white">Premium (set up by the owner)</p>}
      {b.status === "none" && !b.premium_by_owner && <p className="mt-1 text-lg font-semibold text-white">{b.trial_ends_at && b.trial_ends_at * 1000 > Date.now() ? `Free trial until ${dateText(b.trial_ends_at)}` : "No plan yet"}</p>}
      {(b.status === "active" || b.status === "cancelling") && b.period_end && (
        <>
          <p data-testid="current-name" className="mt-1 text-lg font-semibold text-white">{name} · {b.status === "cancelling" ? "ends" : "renews"} {dateText(b.period_end)}</p>
          <p className="mt-1 text-[13.5px] text-[#aab4c6]">{b.status === "cancelling" ? "Renewal is cancelled. You keep access until that date and won't be charged again." : `Next payment: ${inr(price)} on ${dateText(b.period_end)}. Cancel any time and keep access until then.`}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {b.status === "active" && <button type="button" data-testid="cancel-plan" disabled={cancel.isPending} onClick={() => { if (window.confirm(`Cancel renewal? You keep ${name} until ${dateText(b.period_end ?? 0)}.`)) cancel.mutate(); }} className="rounded-lg border border-white/[0.16] px-4 py-2 text-[13px] text-white hover:bg-white/[0.06]">Cancel renewal</button>}
            {b.status === "cancelling" && <button type="button" data-testid="resume-plan" disabled={resume.isPending} onClick={() => resume.mutate()} className="rounded-lg bg-[#e6ebf4] px-4 py-2 text-[13px] font-semibold text-[#070a11]">Keep my plan</button>}
          </div>
          {(cancel.error || resume.error) && <p role="alert" className="mt-3 text-[13px] text-rose-300">{explain(cancel.error ?? resume.error)}</p>}
        </>
      )}
      {b.status === "lapsed" && <p className="mt-1 text-lg font-semibold text-white">{name} ended {b.period_end ? dateText(b.period_end) : ""}</p>}
    </section>
  );
}

// Plans, current status and the controls to pay, renew or cancel. Reachable after the free trial ends, so people can always pay.
export default function Subscription({ expired = false, email, onSignOut }: { expired?: boolean; email?: string | null; onSignOut?: () => void }) {
  const query = useBilling();
  const [plan, setPlan] = useState<"standard" | "premium" | null>(null);
  const b = query.data;
  const premiumNow = !!b?.premium;
  return (
    <div data-testid="subscription-page" className="min-h-screen bg-[#070a11] text-[#e6ebf4]">
      <header className="border-b border-white/[0.06]">
        <div className="mx-auto flex h-16 max-w-[1100px] items-center justify-between px-5 sm:px-8">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-[#e0314b] text-white"><Activity className="size-[18px]" /></span>
            <span className="font-heading text-[15px] font-semibold">EdgeDesk</span>
          </div>
          {expired ? <button type="button" onClick={onSignOut} className="text-[13px] text-[#c3cbda] underline underline-offset-4">Sign out</button> : <Link to="/" className="rounded-md border border-white/[0.14] px-3 py-1.5 text-[13px] text-white hover:bg-white/[0.05]">← Dashboard</Link>}
        </div>
      </header>
      <main className="mx-auto max-w-[1100px] space-y-6 px-5 py-8 pb-24 sm:px-8">
        <div>
          <h1 className="font-heading text-[clamp(1.8rem,4vw,2.6rem)] font-bold tracking-tight">{expired ? "Your free trial has ended" : "Plans and subscription"}</h1>
          {email && <p className="mt-1 text-[13px] text-[#6b778d]">Signed in as {email}</p>}
        </div>
        {query.isPending && <p className="text-sm text-[#8c98ae]">Loading…</p>}
        {query.isError && <p className="text-sm text-[#8c98ae]">Couldn't load your plan right now. Try again shortly.</p>}
        {b && (
          <>
            {b.notices.map((n) => <p key={n.code} data-testid={`notice-${n.code}`} role="status" className={`rounded-xl border px-4 py-3 text-[14px] ${TONE[n.level]}`}>{n.text}</p>)}
            {b.pending_order && (
              <p data-testid="pending-order" role="status" className="rounded-xl border border-amber-300/30 bg-amber-300/[0.08] px-4 py-3 text-[14px] text-amber-100">
                Waiting for your {inr(b.pending_order.amount)} payment (reference <span className="font-mono">{b.pending_order.code}</span>).
                {b.pay_to.upi_id ? ` Pay by UPI to ${b.pay_to.upi_id} and include the reference.` : " The owner will email you the payment details."} Your plan starts once it is confirmed.
              </p>
            )}
            <Current b={b} />
            {!premiumNow && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-300/40 bg-[linear-gradient(135deg,rgba(251,191,36,0.12),rgba(255,255,255,0.02))] p-5">
                <div>
                  <p className="font-heading text-lg font-bold text-white">Upgrade to Premium</p>
                  <p className="text-[13.5px] text-[#d9c58d]">{b.offers.premium.promo ? `Pay ${inr(b.offers.premium.today_inr)} today and your first month of Premium is free. Then ${inr(b.offers.premium.next_charge_inr)} per month until you cancel.` : `${inr(b.offers.premium.today_inr)} per month. Cancel any time.`}</p>
                </div>
                <button type="button" data-testid="upgrade-premium" onClick={() => setPlan("premium")} className="h-11 rounded-xl bg-amber-300 px-6 text-sm font-semibold text-[#1a1203] hover:bg-amber-200">Upgrade to Premium</button>
              </div>
            )}
            <PlanCards
              trialDays={7}
              standardInr={b.offers.standard.today_inr}
              introInr={b.offers.premium.promo ? b.offers.premium.today_inr : 189}
              premiumInr={399}
              actions={{
                standard: { label: b.plan === "standard" && b.status === "active" ? "Renew Standard" : `Continue with Standard · ${inr(b.offers.standard.today_inr)}`, onClick: () => setPlan("standard"), disabled: b.plan === "premium" && b.status !== "lapsed" },
                premium: { label: b.offers.premium.promo ? `Upgrade to Premium · ${inr(b.offers.premium.today_inr)} today` : `Premium · ${inr(b.offers.premium.today_inr)}`, onClick: () => setPlan("premium") },
                current: b.status === "active" || b.status === "cancelling" ? b.plan : null,
              }}
            />
            <Comparison />
            <p className="text-[12px] leading-relaxed text-[#5f6c84]">Prices are in Indian rupees. A month is one calendar month. Cancelling stops renewals and you keep access until the end of the period you paid for. Signals and analysis are information, not investment advice.</p>
          </>
        )}
      </main>
      {plan && b && <CheckoutDialog plan={plan} billing={b} onClose={() => setPlan(null)} />}
    </div>
  );
}
