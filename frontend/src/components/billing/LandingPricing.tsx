import { Comparison, PlanCards } from "@/components/billing/Plans";

interface PublicPlan {
  trial_days: number;
  price_inr: number;
  premium_intro_inr?: number;
  premium_inr?: number;
  signups_open: boolean;
}

// The pricing section of the sign-in page: both plans, what is in them, and the free-trial and first-month terms stated up front.
export default function LandingPricing({ plan, onStart }: { plan: PublicPlan; onStart: () => void }) {
  const intro = plan.premium_intro_inr ?? 189;
  const premium = plan.premium_inr ?? 399;
  const start = plan.signups_open ? `Start ${plan.trial_days}-day free trial` : "Sign in";
  return (
    <section id="pricing" aria-labelledby="pricing-title" className="mx-auto max-w-[1280px] scroll-mt-20 px-5 pb-20 sm:px-8">
      <div className="mx-auto max-w-[720px] text-center">
        <h2 id="pricing-title" className="font-heading text-[clamp(2rem,4vw,3rem)] font-bold leading-tight tracking-tight">Start free. Upgrade when you want more.</h2>
        <p className="mt-3 text-[15px] leading-relaxed text-[#8c98ae]">{plan.trial_days} days of the full Standard dashboard on us, no card needed. Then ₹{plan.price_inr} a month, or step up to Premium for live SENSEX, 129 stocks and the full analysis suite.</p>
      </div>
      <div className="mt-10">
        <PlanCards
          trialDays={plan.trial_days}
          standardInr={plan.price_inr}
          introInr={intro}
          premiumInr={premium}
          actions={{ trial: { label: start, onClick: onStart }, standard: { label: `Start free, then ₹${plan.price_inr}/month`, onClick: onStart }, premium: { label: `Start free, upgrade for ₹${intro}`, onClick: onStart } }}
        />
      </div>
      <div data-testid="pricing-terms" className="mx-auto mt-6 max-w-[860px] rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 text-[13.5px] leading-relaxed text-[#aab4c6]">
        <p className="font-semibold text-white">The terms, in plain words</p>
        <ul className="mt-2 list-disc space-y-1.5 pl-5">
          <li>New accounts get {plan.trial_days} days of the Standard dashboard free. Nothing is charged to start.</li>
          <li>After the trial, Standard is ₹{plan.price_inr} per month.</li>
          <li>Premium upgrade: you pay ₹{intro} and your first month of Premium is free. This offer is once per account.</li>
          <li>After that first month Premium is ₹{premium} per month for the whole dashboard, Standard and Premium features together.</li>
          <li>Before any payment you'll see each amount and date and must tick to agree, including the recurring monthly price. Cancel any time and keep access until the end of the paid period.</li>
        </ul>
      </div>
      <Comparison />
    </section>
  );
}
