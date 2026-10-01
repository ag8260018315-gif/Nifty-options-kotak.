import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { evaluate, MANUAL_ITEMS, type ChainRow, type CheckStatus } from "@/lib/pretrade";

// Risk checks to run through before placing an order in your broker app. The dashboard only checks and
// reminds. It never places orders and never says whether to trade.

type Side = "CE" | "PE";

interface Saved {
  capital: string;
  riskPct: string;
  lotSize: string;
  lots: string;
  limitPrice: string;
  ticks: Record<string, boolean>;
}

const STORAGE_KEY = "nod-pretrade-v1";
const EMPTY: Saved = { capital: "", riskPct: "", lotSize: "", lots: "", limitPrice: "", ticks: {} };

function number(value: string): number | null {
  const parsed = Number(value.replace(/,/g, "").trim());
  return value.trim() !== "" && Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function rupees(value: number) {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const CHIP: Record<CheckStatus, { label: string; className: string }> = {
  flag: { label: "Flag", className: "border-amber-400/40 bg-amber-400/10 text-amber-200" },
  clear: { label: "No flag", className: "border-slate-500/30 bg-slate-500/10 text-slate-300" },
  note: { label: "Note", className: "border-blue-400/30 bg-blue-400/10 text-blue-200" },
};

function Field({ id, label, value, onChange, hint, prefix }: { id: string; label: string; value: string; onChange: (value: string) => void; hint?: string; prefix?: string }) {
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] text-slate-400">{label}</label>
      <div className="mt-1 flex items-center rounded-md border border-[#2a364f] bg-[#0e131d] focus-within:border-blue-500">
        {prefix && <span className="pl-2.5 text-xs text-slate-500">{prefix}</span>}
        <input id={id} data-testid={id} inputMode="decimal" autoComplete="off" value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full min-w-0 bg-transparent px-2.5 text-sm text-slate-100 outline-none placeholder:text-slate-600" />
      </div>
      {hint && <p className="mt-1 text-[10px] text-slate-600">{hint}</p>}
    </div>
  );
}

export default function PreTradeChecks({ symbol, rows, expiry, feedState, lastTick }: { symbol: string; rows: ChainRow[]; expiry: string | undefined; feedState: string; lastTick: string | null }) {
  const [side, setSide] = useState<Side>("CE");
  const [strike, setStrike] = useState<number | null>(null);
  const [saved, setSaved] = useState<Saved>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setSaved({ ...EMPTY, ...(JSON.parse(raw) as Partial<Saved>) });
    } catch {
      // Storage can be unavailable (private browsing); the checks still work without it.
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    } catch {
      // ignore
    }
  }, [saved, loaded]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const sorted = useMemo(() => [...rows].sort((a, b) => a.strike - b.strike), [rows]);
  const atmStrike = sorted.find((row) => row.is_atm)?.strike ?? sorted[Math.floor(sorted.length / 2)]?.strike ?? null;
  const activeStrike = strike !== null && sorted.some((row) => row.strike === strike) ? strike : atmStrike;
  const lastTickMs = lastTick ? Date.parse(lastTick) : NaN;

  const result = useMemo(
    () =>
      evaluate({
        rows: sorted,
        strike: activeStrike,
        side,
        feedState,
        lastTickMs: Number.isFinite(lastTickMs) ? lastTickMs : null,
        nowMs: now,
        expiry,
        inputs: { capital: number(saved.capital), riskPct: number(saved.riskPct), lotSize: number(saved.lotSize), lots: number(saved.lots), limitPrice: number(saved.limitPrice) },
      }),
    [sorted, activeStrike, side, feedState, lastTickMs, now, expiry, saved],
  );

  const flagged = result.checks.filter((check) => check.status === "flag").length;
  const ticked = MANUAL_ITEMS.filter((item) => saved.ticks[item.id]).length;
  const set = (key: keyof Omit<Saved, "ticks">) => (value: string) => setSaved((current) => ({ ...current, [key]: value }));
  const sizing = result.sizing;

  return (
    <Card data-testid="pretrade-card" className="border-[#202b42] bg-[#0c0f17]/95">
      <CardHeader className="border-b border-[#202b42] px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle data-testid="pretrade-title" className="font-heading text-base text-slate-100">Pre-trade checks</CardTitle>
            <p className="mt-1 max-w-[62ch] text-xs leading-relaxed text-slate-500">Run through these before you place any order in your broker app. This dashboard only checks. It never places orders and it doesn't tell you whether to trade.</p>
          </div>
          <div className="text-right">
            <p data-testid="pretrade-flag-count" className={`text-sm font-semibold ${flagged ? "text-amber-200" : "text-slate-300"}`}>{flagged === 0 ? "No automatic flags" : `${flagged} ${flagged === 1 ? "flag" : "flags"} to look at`}</p>
            <p className="mt-0.5 text-[10px] text-slate-600">No flags is not a go-ahead.</p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6 p-4 sm:p-5">
        <section aria-labelledby="pt-contract" className="space-y-3">
          <h3 id="pt-contract" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">1. The contract</h3>
          <div className="flex flex-wrap items-end gap-3">
            <div role="group" aria-label="Option side" className="flex rounded-md border border-[#2a364f] p-0.5">
              {(["CE", "PE"] as Side[]).map((option) => (
                <button key={option} type="button" aria-pressed={side === option} data-testid={`pretrade-side-${option}`} onClick={() => setSide(option)} className={`rounded px-3 py-1.5 text-xs font-semibold ${side === option ? "bg-[#1f2a41] text-white" : "text-slate-400 hover:text-slate-200"}`}>
                  {option === "CE" ? "Call (CE)" : "Put (PE)"}
                </button>
              ))}
            </div>
            <div>
              <label htmlFor="pretrade-strike" className="block text-[11px] text-slate-400">Strike</label>
              <select id="pretrade-strike" data-testid="pretrade-strike" value={activeStrike ?? ""} onChange={(event) => setStrike(Number(event.target.value))} disabled={!sorted.length} className="mt-1 h-9 rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 text-sm text-slate-100 outline-none focus:border-blue-500 disabled:opacity-50">
                {sorted.map((row) => <option key={row.strike} value={row.strike}>{row.strike}{row.is_atm ? " (ATM)" : ""}</option>)}
              </select>
            </div>
            <p className="pb-2 text-xs text-slate-500">{symbol}{expiry ? `, expiry ${expiry}` : ""}{result.ltp ? <> · last traded price <span data-testid="pretrade-ltp" className="font-mono text-slate-200">₹{result.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span></> : null}</p>
          </div>
        </section>

        <section aria-labelledby="pt-numbers" className="space-y-3">
          <h3 id="pt-numbers" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">2. Your numbers</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Field id="pretrade-capital" label="Your trading capital" prefix="₹" value={saved.capital} onChange={set("capital")} />
            <Field id="pretrade-risk" label="Most you accept to lose on one trade" prefix="%" value={saved.riskPct} onChange={set("riskPct")} hint="Of your capital" />
            <Field id="pretrade-lotsize" label="Lot size" value={saved.lotSize} onChange={set("lotSize")} hint="From your broker app. It changes over time." />
            <Field id="pretrade-lots" label="Number of lots" value={saved.lots} onChange={set("lots")} />
            <Field id="pretrade-price" label="Price you plan to use" prefix="₹" value={saved.limitPrice} onChange={set("limitPrice")} hint="Leave empty to use the last price" />
          </div>
          {sizing && (
            <dl data-testid="pretrade-sizing" className="grid grid-cols-2 gap-3 rounded-lg border border-[#202b42] bg-[#090d15] p-3 text-xs sm:grid-cols-4">
              <div><dt className="text-slate-500">Cost of the position</dt><dd className="mt-0.5 font-mono text-sm text-slate-100">{rupees(sizing.cost)}</dd></div>
              <div><dt className="text-slate-500">Share of your capital</dt><dd className="mt-0.5 font-mono text-sm text-slate-100">{sizing.costPctOfCapital === null ? "—" : `${sizing.costPctOfCapital.toFixed(1)}%`}</dd></div>
              <div><dt className="text-slate-500">Your risk limit</dt><dd className="mt-0.5 font-mono text-sm text-slate-100">{sizing.riskBudget === null ? "—" : rupees(sizing.riskBudget)}</dd></div>
              <div><dt className="text-slate-500">Lots that fit your limit</dt><dd className="mt-0.5 font-mono text-sm text-slate-100">{sizing.lotsAllowed === null ? "—" : sizing.lotsAllowed}</dd></div>
            </dl>
          )}
          <p className="text-[10px] leading-relaxed text-slate-600">These numbers work for buying options, where the most you can lose is the premium you pay. Selling options can lose far more than the premium, and these checks do not cover that.</p>
        </section>

        <section aria-labelledby="pt-auto" className="space-y-3">
          <h3 id="pt-auto" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">3. Automatic checks from live data</h3>
          <ul data-testid="pretrade-checks" className="divide-y divide-[#1a2336] rounded-lg border border-[#202b42]">
            {result.checks.map((check) => (
              <li key={check.id} data-testid={`pretrade-check-${check.id}`} className="flex items-start gap-3 px-3 py-3">
                <span className={`mt-0.5 inline-flex w-[58px] shrink-0 justify-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${CHIP[check.status].className}`}>{CHIP[check.status].label}</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-100">{check.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{check.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="pt-manual" className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 id="pt-manual" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">4. Your own checklist</h3>
            <p data-testid="pretrade-ticked" className="text-xs text-slate-500">{ticked} of {MANUAL_ITEMS.length} ticked</p>
          </div>
          <ul className="space-y-2">
            {MANUAL_ITEMS.map((item) => (
              <li key={item.id}>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-[#202b42] bg-[#0e131d] px-3 py-2.5 text-xs leading-relaxed text-slate-300 hover:border-[#2c3a57]">
                  <input type="checkbox" data-testid={`pretrade-tick-${item.id}`} checked={Boolean(saved.ticks[item.id])} onChange={(event) => setSaved((current) => ({ ...current, ticks: { ...current.ticks, [item.id]: event.target.checked } }))} className="mt-0.5 size-4 shrink-0 accent-blue-500" />
                  <span>{item.text}</span>
                </label>
              </li>
            ))}
          </ul>
        </section>

        <div className="space-y-2 border-t border-[#202b42] pt-4">
          <p className="text-[11px] leading-relaxed text-slate-500">Most individual traders in index options lose money. SEBI's study of FY2025-26 found that 87.7% of the traders in its sample ended the year with a net loss. These checks reduce avoidable mistakes. They do not make a trade profitable.</p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[10px] text-slate-600">Your numbers and ticks are saved only in this browser.</p>
            <Button data-testid="pretrade-clear" type="button" variant="outline" size="sm" className="h-7 border-[#2a364f] bg-transparent text-[11px] text-slate-400" onClick={() => setSaved(EMPTY)}>Clear my numbers</Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
