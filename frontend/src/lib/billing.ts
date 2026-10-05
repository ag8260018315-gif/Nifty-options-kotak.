import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "@/lib/api";

// Plans and subscriptions. The server decides what has been paid for and writes every term shown here; the pages only display it.

export interface Terms {
  plan: "standard" | "premium";
  kind: "standard" | "premium" | "premium_intro";
  today_inr: number;
  period_start: number;
  period_end: number;
  next_charge_inr: number;
  next_charge_on: string;
  next_charge_label: string;
  promo: boolean;
  auto_renew: boolean;
  terms_version: string;
  lines: string[];
}

export interface Notice {
  level: "info" | "warn" | "error";
  code: string;
  text: string;
}

export interface PendingOrder {
  id: string;
  code: string;
  plan: string;
  amount: number;
  created_at: number;
}

export interface Billing {
  email: string | null;
  status: "none" | "active" | "cancelling" | "lapsed";
  plan: "standard" | "premium" | null;
  period_end: number | null;
  cancel_at_period_end: boolean;
  premium: boolean;
  premium_by_owner: boolean;
  trial_ends_at: number | null;
  role: string | null;
  promo_used: boolean;
  offers: { standard: Terms; premium: Terms };
  notices: Notice[];
  payments_live: boolean;
  pay_to: { upi_id?: string; payee?: string };
  pending_order: PendingOrder | null;
}

export interface Checkout {
  order: PendingOrder;
  pay_to: { upi_id?: string; payee?: string };
  terms: Terms;
}

export const BILLING_KEY = ["billing-me"];
export const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;
export const dateText = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });

export function useBilling(enabled = true) {
  return useQuery({ queryKey: BILLING_KEY, queryFn: () => apiGet<Billing>("/billing/me"), enabled, refetchInterval: 60_000, retry: false });
}

export function useBillingActions() {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: BILLING_KEY });
    void client.invalidateQueries({ queryKey: ["access-me"] });
  };
  const checkout = useMutation({
    mutationFn: ({ plan, terms }: { plan: "standard" | "premium"; terms: Terms }) =>
      apiPost<Checkout>("/billing/checkout", {
        plan,
        consent: { accept_terms: true, accept_recurring: true, terms_version: terms.terms_version, today_inr: terms.today_inr, next_charge_inr: terms.next_charge_inr, next_charge_on: terms.next_charge_on },
      }),
    onSuccess: refresh,
  });
  const cancel = useMutation({ mutationFn: () => apiPost("/billing/cancel"), onSuccess: refresh });
  const resume = useMutation({ mutationFn: () => apiPost("/billing/resume"), onSuccess: refresh });
  return { checkout, cancel, resume };
}

// What each plan really contains. Everything listed exists in the app today; nothing here is a promise of future features.
export const STANDARD_FEATURES = [
  "Live NIFTY, BANKNIFTY and FINNIFTY from the Kotak Neo feed",
  "Option chain, ATM ±10 strikes, OI and change in OI",
  "Greeks: IV, delta, gamma, theta, vega (model estimates)",
  "PCR and OI analytics, max pain, OI build-up",
  "Live charts and analytics for each index",
  "AI market analyst that explains the data",
  "CSV export of verified snapshots",
];

export const PREMIUM_FEATURES = [
  "Everything in Standard",
  "Live SENSEX prices and charts with analytics",
  "Live prices and charts for 129 supported stocks during market hours",
  "A page for every stock: chart, 9 and 20 EMA (adjustable), RSI, MACD, VWAP, Bollinger Bands",
  "Buying versus selling pressure, relative volume and candlestick patterns",
  "Trade setups with entry, stop and targets, plus a signal score with its tested history",
  "Stock news and exchange announcements with a keyword reading of the tone",
  "Stock comparison, watchlists, saved chart layouts",
  "Price and signal alerts, sector heatmap and a daily market recap",
];

export const COMPARE_ROWS: { label: string; trial: boolean; standard: boolean; premium: boolean }[] = [
  { label: "NIFTY, BANKNIFTY, FINNIFTY live data and charts", trial: true, standard: true, premium: true },
  { label: "Option chain, Greeks, PCR and OI analytics", trial: true, standard: true, premium: true },
  { label: "AI market analyst and CSV export", trial: true, standard: true, premium: true },
  { label: "Live SENSEX data and charts", trial: false, standard: false, premium: true },
  { label: "Live prices and charts for 129 stocks", trial: false, standard: false, premium: true },
  { label: "Stock pages with 9 / 20 EMA, RSI, MACD, VWAP", trial: false, standard: false, premium: true },
  { label: "Buyer-versus-seller pressure, patterns and setups", trial: false, standard: false, premium: true },
  { label: "Signal score with tested history", trial: false, standard: false, premium: true },
  { label: "Stock news and announcements", trial: false, standard: false, premium: true },
  { label: "Alerts, sector heatmap, daily recap, watchlists", trial: false, standard: false, premium: true },
];
