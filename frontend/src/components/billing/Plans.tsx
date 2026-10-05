import { COMPARE_ROWS, inr, PREMIUM_FEATURES, STANDARD_FEATURES } from "@/lib/billing";

const Tick = ({ ok }: { ok: boolean }) =>
  ok ? (
    <svg aria-label="Included" role="img" viewBox="0 0 16 16" className="mx-auto size-4 text-emerald-300"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
  ) : (
    <span aria-label="Not included" role="img" className="text-slate-600">—</span>
  );

function Features({ items, tone }: { items: string[]; tone: "emerald" | "amber" }) {
  return (
    <ul className="mt-5 space-y-2.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2.5 text-[13.5px] leading-snug text-[#d5dbe6]">
          <svg aria-hidden="true" viewBox="0 0 16 16" className={`mt-0.5 size-4 shrink-0 ${tone === "amber" ? "text-amber-300" : "text-emerald-300"}`}><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          {item}
        </li>
      ))}
    </ul>
  );
}

export interface PlanActions {
  trial?: { label: string; onClick: () => void } | null;
  standard: { label: string; onClick: () => void; disabled?: boolean } | null;
  premium: { label: string; onClick: () => void; disabled?: boolean } | null;
  current?: "standard" | "premium" | null;
}

// The three plans side by side. Used on the sign-in page and inside the dashboard, so the wording can never drift apart.
export function PlanCards({ trialDays, standardInr, introInr, premiumInr, actions }: { trialDays: number; standardInr: number; introInr: number; premiumInr: number; actions: PlanActions }) {
  const button = "mt-6 h-11 w-full rounded-xl text-[14px] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 disabled:opacity-50";
  return (
    <div data-testid="plan-cards" className="grid gap-4 lg:grid-cols-3">
      <section aria-labelledby="plan-trial" className="flex flex-col rounded-2xl border border-white/[0.08] bg-white/[0.02] p-6">
        <h3 id="plan-trial" className="text-[13px] font-semibold uppercase tracking-[0.16em] text-[#8c98ae]">Free trial</h3>
        <p className="mt-3 font-heading text-4xl font-bold tracking-tight text-white">{inr(0)}</p>
        <p className="mt-1 text-[13px] text-[#8c98ae]">for {trialDays} days, new accounts</p>
        <p className="mt-4 text-[13.5px] leading-relaxed text-[#aab4c6]">The full Standard dashboard. No card needed. Premium features are not part of the trial.</p>
        <div className="flex-1" />
        {actions.trial && <button type="button" data-testid="plan-trial-cta" onClick={actions.trial.onClick} className={`${button} border border-white/[0.14] text-white hover:bg-white/[0.05]`}>{actions.trial.label}</button>}
      </section>

      <section aria-labelledby="plan-standard" data-testid="plan-standard" className="flex flex-col rounded-2xl border border-white/[0.08] bg-white/[0.02] p-6">
        <h3 id="plan-standard" className="text-[13px] font-semibold uppercase tracking-[0.16em] text-emerald-300">Standard</h3>
        <p className="mt-3 font-heading text-4xl font-bold tracking-tight text-white">{inr(standardInr)}<span className="ml-1 text-base font-medium text-[#8c98ae]">/ month</span></p>
        <p className="mt-1 text-[13px] text-[#8c98ae]">after the {trialDays}-day free trial</p>
        <Features items={STANDARD_FEATURES} tone="emerald" />
        <div className="flex-1" />
        {actions.standard && <button type="button" data-testid="plan-standard-cta" disabled={actions.standard.disabled} onClick={actions.standard.onClick} className={`${button} bg-[#e6ebf4] text-[#070a11] hover:opacity-90`}>{actions.current === "standard" ? "Your current plan" : actions.standard.label}</button>}
      </section>

      <section aria-labelledby="plan-premium" data-testid="plan-premium" className="relative flex flex-col rounded-2xl border border-amber-300/40 bg-[linear-gradient(160deg,rgba(251,191,36,0.10),rgba(255,255,255,0.015))] p-6 shadow-[0_0_40px_rgba(251,191,36,0.07)]">
        <span className="absolute -top-3 left-6 rounded-full bg-amber-300 px-3 py-0.5 text-[11px] font-bold uppercase tracking-wider text-[#1a1203]">First month free</span>
        <h3 id="plan-premium" className="text-[13px] font-semibold uppercase tracking-[0.16em] text-amber-300">Premium</h3>
        <p className="mt-3 font-heading text-4xl font-bold tracking-tight text-white">{inr(introInr)}<span className="ml-1 text-base font-medium text-[#c9b27a]">to upgrade today</span></p>
        <p data-testid="premium-terms-short" className="mt-1 text-[13px] leading-relaxed text-[#d9c58d]">Your first month of Premium is free. After that, {inr(premiumInr)} per month until you cancel.</p>
        <Features items={PREMIUM_FEATURES} tone="amber" />
        <div className="flex-1" />
        {actions.premium && <button type="button" data-testid="plan-premium-cta" disabled={actions.premium.disabled} onClick={actions.premium.onClick} className={`${button} bg-amber-300 text-[#1a1203] hover:bg-amber-200`}>{actions.current === "premium" ? "Your current plan" : actions.premium.label}</button>}
        <p className="mt-3 text-[11.5px] leading-relaxed text-[#a89868]">Offer is once per account. You'll see the exact amounts and dates, and be asked to agree, before anything is paid.</p>
      </section>
    </div>
  );
}

export function Comparison() {
  return (
    <div data-testid="plan-compare" className="mt-8 overflow-x-auto rounded-2xl border border-white/[0.08]">
      <table className="w-full min-w-[560px] text-left text-[13.5px]">
        <caption className="sr-only">What each plan includes</caption>
        <thead>
          <tr className="border-b border-white/[0.08] text-[12px] uppercase tracking-wider text-[#8c98ae]">
            <th scope="col" className="px-4 py-3 font-semibold">Feature</th>
            <th scope="col" className="px-3 py-3 text-center font-semibold">Trial</th>
            <th scope="col" className="px-3 py-3 text-center font-semibold text-emerald-300">Standard</th>
            <th scope="col" className="px-3 py-3 text-center font-semibold text-amber-300">Premium</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.05]">
          {COMPARE_ROWS.map((row) => (
            <tr key={row.label}>
              <th scope="row" className="px-4 py-3 font-normal text-[#d5dbe6]">{row.label}</th>
              <td className="px-3 py-3 text-center"><Tick ok={row.trial} /></td>
              <td className="px-3 py-3 text-center"><Tick ok={row.standard} /></td>
              <td className="px-3 py-3 text-center"><Tick ok={row.premium} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
