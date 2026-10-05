import { Link } from "react-router-dom";

import { useBilling } from "@/lib/billing";

const TONE = { info: "border-sky-400/25 bg-sky-400/[0.07] text-sky-100", warn: "border-amber-300/30 bg-amber-300/[0.08] text-amber-100", error: "border-rose-400/30 bg-rose-400/[0.08] text-rose-100" };

// A slim message across the dashboard when something about the plan needs attention: trial ending, lapsed plan, failed payment.
export default function PlanBanner() {
  const { data } = useBilling();
  const notice = data?.notices[0];
  if (!notice) return null;
  return (
    <div data-testid="plan-banner" role="status" className={`flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2 text-[13px] ${TONE[notice.level]}`}>
      <span data-testid="plan-banner-text">{notice.text}</span>
      <Link to="/subscription" data-testid="plan-banner-link" className="rounded-md border border-current px-3 py-1 text-[12px] font-semibold hover:bg-white/10">See plans</Link>
    </div>
  );
}
