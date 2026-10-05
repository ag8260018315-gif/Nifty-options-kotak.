import { useState } from "react";

import { explain } from "@/lib/exchange";
import { dateText, inr, useBillingActions, type Billing, type Checkout } from "@/lib/billing";

// The step before any payment: every amount and date in plain words, and two separate ticks of consent.
export default function CheckoutDialog({ plan, billing, onClose }: { plan: "standard" | "premium"; billing: Billing; onClose: () => void }) {
  const terms = billing.offers[plan];
  const { checkout } = useBillingActions();
  const [terms1, setTerms1] = useState(false);
  const [terms2, setTerms2] = useState(false);
  const [done, setDone] = useState<Checkout | null>(null);
  const name = plan === "premium" ? "Premium" : "Standard";
  return (
    <div role="dialog" aria-modal="true" aria-label={`Subscribe to ${name}`} data-testid="checkout" className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-6">
      <div className="max-h-[92vh] w-full max-w-[520px] overflow-y-auto rounded-t-3xl border border-white/[0.1] bg-[#0b0f18] p-6 text-[#e6ebf4] sm:rounded-3xl">
        {done ? (
          <div data-testid="checkout-done" className="space-y-3">
            <h2 className="font-heading text-xl font-bold">Almost there: pay {inr(done.order.amount)}</h2>
            <p className="text-sm leading-relaxed text-[#aab4c6]">Your reference is <span data-testid="order-code" className="rounded bg-white/[0.08] px-1.5 py-0.5 font-mono text-white">{done.order.code}</span>. Include it in the payment note so we can match it.</p>
            {done.pay_to.upi_id ? (
              <p className="rounded-xl border border-white/[0.1] bg-white/[0.03] p-3 text-sm">Pay {inr(done.order.amount)} by UPI to <span className="font-mono font-semibold text-white">{done.pay_to.upi_id}</span>{done.pay_to.payee ? ` (${done.pay_to.payee})` : ""}.</p>
            ) : (
              <p className="rounded-xl border border-white/[0.1] bg-white/[0.03] p-3 text-sm">The owner will email you the payment details shortly.</p>
            )}
            <p className="text-[13px] leading-relaxed text-[#8c98ae]">Your {name} plan starts as soon as the payment is confirmed, usually within a day. Nothing is charged automatically. Until then your access stays as it is.</p>
            <button type="button" onClick={onClose} className="h-11 w-full rounded-xl bg-[#e6ebf4] text-sm font-semibold text-[#070a11]">Done</button>
          </div>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); checkout.mutate({ plan, terms }, { onSuccess: setDone }); }} className="space-y-4">
            <h2 className="font-heading text-xl font-bold">{terms.promo ? "Upgrade to Premium" : `Continue with ${name}`}</h2>
            <div data-testid="checkout-summary" className="rounded-2xl border border-amber-300/30 bg-amber-300/[0.06] p-4">
              <p className="text-[12px] uppercase tracking-wider text-amber-200/80">You pay today</p>
              <p className="font-heading text-3xl font-bold text-white">{inr(terms.today_inr)}</p>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
                <dt className="text-[#a89868]">Plan runs until</dt><dd className="text-right text-white">{dateText(terms.period_end)}</dd>
                <dt className="text-[#a89868]">Next payment</dt><dd data-testid="checkout-next" className="text-right text-white">{inr(terms.next_charge_inr)} on {terms.next_charge_label}</dd>
                <dt className="text-[#a89868]">Then</dt><dd className="text-right text-white">{inr(terms.next_charge_inr)} every month until you cancel</dd>
              </dl>
            </div>
            <ul className="list-disc space-y-1.5 pl-5 text-[13.5px] leading-relaxed text-[#c3cbda]">{terms.lines.map((l) => <li key={l}>{l}</li>)}</ul>
            <label className="flex gap-2.5 text-[13.5px] leading-snug text-[#d5dbe6]">
              <input data-testid="consent-terms" type="checkbox" className="mt-0.5 size-4 shrink-0" checked={terms1} onChange={(e) => setTerms1(e.target.checked)} />
              <span>I have read the terms above. I will pay {inr(terms.today_inr)} today for a plan that runs until {dateText(terms.period_end)}.</span>
            </label>
            <label className="flex gap-2.5 text-[13.5px] leading-snug text-[#d5dbe6]">
              <input data-testid="consent-recurring" type="checkbox" className="mt-0.5 size-4 shrink-0" checked={terms2} onChange={(e) => setTerms2(e.target.checked)} />
              <span>I agree that from {terms.next_charge_label} the plan renews at {inr(terms.next_charge_inr)} per month until I cancel{terms.auto_renew ? ", charged automatically" : ", and that each renewal payment will be requested from me"}.</span>
            </label>
            {checkout.error && <p data-testid="checkout-error" role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[13px] text-rose-200">{explain(checkout.error)}</p>}
            <div className="flex gap-2">
              <button type="submit" data-testid="checkout-submit" disabled={!terms1 || !terms2 || checkout.isPending} className="h-11 flex-1 rounded-xl bg-amber-300 text-sm font-semibold text-[#1a1203] hover:bg-amber-200 disabled:opacity-40">{checkout.isPending ? "Please wait…" : `Agree and pay ${inr(terms.today_inr)}`}</button>
              <button type="button" onClick={onClose} className="h-11 rounded-xl border border-white/[0.14] px-4 text-sm text-[#c3cbda] hover:bg-white/[0.05]">Cancel</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
