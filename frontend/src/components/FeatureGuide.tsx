import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// A short guide to what the desk offers. Each card jumps to the matching part of this page.
// Keep every line true to what the dashboard really does: this is the product's own description of itself.

interface Feature {
  title: string;
  brief: string;
  target: string | null; // id of the section to jump to
  where: string;
  ownerOnly?: boolean;
}

interface Group {
  name: string;
  features: Feature[];
}

export const GROUPS: Group[] = [
  {
    name: "Live market",
    features: [
      { title: "Live index prices", brief: "NIFTY 50, BANKNIFTY and FINNIFTY from your Kotak Neo feed, refreshed about every second. Switch index without reloading.", target: "overview", where: "Overview" },
      { title: "Index overview", brief: "Price, change, open, previous close, high, low, ATM strike and expiry, with a clear market open or closed status.", target: "overview", where: "Overview" },
      { title: "Live candle chart", brief: "1, 5 and 15 minute candles built from live ticks, with the last 5 and 15 minute moves.", target: "chart", where: "Chart" },
      { title: "Candle pattern markers", brief: "Marks a candle that was followed by a much larger move, and tracks whether price came back. A chart pattern, not order data.", target: "chart", where: "Chart" },
    ],
  },
  {
    name: "Options data",
    features: [
      { title: "Option chain", brief: "Strikes around ATM with open interest, OI change, volume, IV, delta and last price for calls and puts. Search a strike, switch to compact view, see the heaviest OI.", target: "option-chain", where: "Option chain" },
      { title: "PCR and open interest", brief: "Put-call ratio, call and put totals, and the strikes where open interest is highest.", target: "overview", where: "Overview" },
      { title: "Greeks ladder", brief: "IV, delta, gamma, theta and vega for each strike. These are model estimates, not exchange figures.", target: "greeks", where: "Greeks" },
    ],
  },
  {
    name: "Signals and research",
    features: [
      { title: "How it works", brief: "An animated picture of the two engines: research tunes the settings from past data, and the live engine turns today's market into a signal.", target: "how", where: "How it works" },
      { title: "Live signal", brief: "A CE or PE signal with the chosen strike, stop and target, built only from current data. It shows its own confidence, and is blocked if the data is stale or from the future.", target: "signals", where: "Live signal" },
      { title: "Auto-trader (practice)", brief: "Takes each live signal as a practice trade with pretend money, applies stop, target, daily-loss and square-off limits, and shows the profit and loss. No order reaches Kotak. The owner can stop it with one button.", target: "trader", where: "Auto-trader" },
      { title: "Research and validation", brief: "Past candles are used to tune and test the rules on days they were not tuned on. The result is the historical validated accuracy, a separate number from live confidence.", target: "research", where: "Research" },
    ],
  },
  {
    name: "Analysis and checks",
    features: [
      { title: "Market readings", brief: "PCR lean, the last 5 and 15 minute moves and the 15 minute high and low, shown as plain readings. No recommendation.", target: "indicators", where: "Indicators" },
      { title: "Pre-trade checks", brief: "Risk checks before you place an order in your broker app: market session, data freshness, liquidity, expiry, time decay, and position size against your own limit. Plus a checklist of your own.", target: "checks", where: "Pre-trade checks" },
      { title: "AI Market Analyst", brief: "Claude explains the live chain in plain words with five insight cards and questions you can ask. Every figure it quotes is checked against your data first.", target: "ai", where: "AI analyst" },
    ],
  },
  {
    name: "Alerts and records",
    features: [
      { title: "Alerts", brief: "Notices when the ATM strike shifts, on expiry day and near the close. Set your own sensitivity, cooldown and quiet hours. Browser notifications are optional.", target: "alerts", where: "Alert controls" },
      { title: "CSV exports", brief: "Download each index's verified snapshots for the day. The closing archive is prepared automatically after 15:31 IST.", target: "export", where: "Exports" },
    ],
  },
  {
    name: "Your account",
    features: [
      { title: "Sign-in and free trial", brief: "Sign in with a code sent to your email, with no password to remember. New accounts start with a free trial.", target: null, where: "Bottom bar" },
      { title: "Owner tools", brief: "Connect your Kotak Neo session and approve who can sign in, from the Access button in the bottom bar.", target: null, where: "Bottom bar, Access", ownerOnly: true },
    ],
  },
];

function Body({ feature }: { feature: Feature }) {
  return (
    <>
      <p className="text-sm font-medium text-slate-100">{feature.title}</p>
      <p className="mt-1 text-xs leading-relaxed text-slate-400">{feature.brief}</p>
      <p className="mt-2 text-[11px] text-slate-500">{feature.target ? <><span aria-hidden="true">Go to </span><span className="text-blue-300">{feature.where}</span><span aria-hidden="true"> →</span></> : feature.where}</p>
    </>
  );
}

export default function FeatureGuide({ isOwner }: { isOwner: boolean }) {
  return (
    <Card data-testid="feature-guide" className="border-[#202b42] bg-[#0c0f17]/95">
      <CardHeader className="border-b border-[#202b42] px-4 py-4 sm:px-5">
        <CardTitle data-testid="feature-guide-title" className="font-heading text-base text-slate-100">What this desk offers</CardTitle>
        <p className="mt-1 max-w-[70ch] text-xs leading-relaxed text-slate-500">Read-only options analytics for NIFTY, BANKNIFTY and FINNIFTY, built on your Kotak Neo feed. A quick guide to everything on this page. Tap a card to jump to it.</p>
      </CardHeader>
      <CardContent className="space-y-6 p-4 sm:p-5">
        {GROUPS.map((group) => {
          const features = group.features.filter((feature) => !feature.ownerOnly || isOwner);
          return (
            <section key={group.name} aria-label={group.name}>
              <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{group.name}</h3>
              <ul className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {features.map((feature) => (
                  <li key={feature.title}>
                    {feature.target ? (
                      <a href={`#${feature.target}`} data-testid={`guide-${feature.title.toLowerCase().replace(/[^a-z]+/g, "-")}`} className="block h-full rounded-lg border border-[#202b42] bg-[#0e131d] p-3 transition-colors hover:border-blue-400/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/50">
                        <Body feature={feature} />
                      </a>
                    ) : (
                      <div data-testid={`guide-${feature.title.toLowerCase().replace(/[^a-z]+/g, "-")}`} className="h-full rounded-lg border border-[#202b42] bg-[#0e131d] p-3">
                        <Body feature={feature} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        <p data-testid="feature-guide-note" className="border-t border-[#202b42] pt-4 text-[11px] leading-relaxed text-slate-500">
          This dashboard is read-only: it never places, changes or cancels orders. Prices and option data come from the Kotak Neo feed. IV and the Greeks are model estimates. Nothing here is investment advice, and AI and pattern output can be wrong.
        </p>
      </CardContent>
    </Card>
  );
}
