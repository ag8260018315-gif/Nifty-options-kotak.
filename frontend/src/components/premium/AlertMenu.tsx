import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { ALERT_LABEL, alertText, type AlertKind } from "@/lib/premium";
import { useAlerts } from "@/lib/premiumData";

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
  }
  return "That didn't go through. Try again shortly.";
}

export const NO_VALUE: AlertKind[] = ["bias_bullish", "bias_bearish"];

// Create an alert for one stock and see the ones it already has.
export default function AlertMenu({ symbol, price }: { symbol: string; price: number | null }) {
  const store = useAlerts();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<AlertKind>("price_above");
  const [value, setValue] = useState("");
  const [once, setOnce] = useState(true);
  const [email, setEmail] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const mine = store.alerts.filter((a) => a.symbol === symbol);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const submit = async () => {
    const needsValue = !NO_VALUE.includes(kind);
    const number = Number(value);
    if (needsValue && (value.trim() === "" || !Number.isFinite(number))) {
      setProblem("Enter a number for the alert level.");
      return;
    }
    try {
      await store.create({ symbol, kind, ...(needsValue ? { value: number } : {}), once, email });
      setValue("");
      setProblem(null);
    } catch (error) {
      setProblem(explain(error));
    }
  };

  return (
    <div className="relative">
      <button type="button" data-testid="alert-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)} className={`h-8 rounded-md border px-3 text-xs ${mine.some((a) => a.active) ? "border-amber-300/50 bg-amber-300/10 text-amber-200" : "border-[#26334b] text-slate-300 hover:bg-[#1a2336]"}`}>🔔 Alert{mine.length ? ` (${mine.length})` : ""}</button>
      {open && (
        <div data-testid="alert-panel" role="group" aria-label={`Alerts for ${symbol}`} className="absolute left-0 z-20 mt-1 w-80 max-w-[88vw] rounded-lg border border-[#2a364f] bg-[#0e131d] p-3 shadow-xl sm:left-auto sm:right-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">New alert for {symbol}</p>
          <form className="mt-2 space-y-2" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
            <select data-testid="alert-kind" value={kind} onChange={(event) => setKind(event.target.value as AlertKind)} aria-label="Alert type" className="h-8 w-full rounded-md border border-[#2a364f] bg-[#0b0f17] px-2 text-xs text-slate-200">
              {(Object.keys(ALERT_LABEL) as AlertKind[]).map((k) => <option key={k} value={k}>{ALERT_LABEL[k]}</option>)}
            </select>
            {!NO_VALUE.includes(kind) && <input data-testid="alert-value" inputMode="decimal" value={value} onChange={(event) => setValue(event.target.value)} placeholder={kind.startsWith("price") && price ? `e.g. ${price}` : "Level"} aria-label="Alert level" className="h-8 w-full rounded-md border border-[#2a364f] bg-[#0b0f17] px-2 text-xs text-slate-200 placeholder:text-slate-600" />}
            <label className="flex items-center gap-2 text-[11px] text-slate-300"><input type="checkbox" checked={once} onChange={(event) => setOnce(event.target.checked)} className="size-3.5 accent-amber-300" /> Alert once, then switch off</label>
            <label className="flex items-center gap-2 text-[11px] text-slate-300"><input type="checkbox" data-testid="alert-email" checked={email} onChange={(event) => setEmail(event.target.checked)} className="size-3.5 accent-amber-300" /> Also email me</label>
            <button type="submit" data-testid="alert-save" disabled={store.busy} className="h-8 w-full rounded-md bg-amber-300 text-xs font-semibold text-[#1a1203] hover:bg-amber-200 disabled:opacity-60">Create alert</button>
          </form>
          {(problem || store.error) && <p role="alert" className="mt-1 text-[11px] text-rose-300">{problem ?? explain(store.error)}</p>}
          {mine.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-[#202b42] pt-2">
              {mine.map((a) => (
                <li key={a.id} className="flex items-center gap-2 text-[11px] text-slate-300">
                  <span className={`min-w-0 flex-1 ${a.active ? "" : "text-slate-500 line-through"}`}>{alertText(a)}</span>
                  <button type="button" onClick={() => void store.toggle({ id: a.id, active: !a.active })} className="rounded px-1.5 py-0.5 text-sky-300 hover:bg-[#1a2336]">{a.active ? "Pause" : "Resume"}</button>
                  <button type="button" aria-label="Delete alert" onClick={() => void store.remove(a.id)} className="rounded px-1.5 py-0.5 text-slate-500 hover:text-rose-300">×</button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[10px] leading-snug text-slate-600">Checked against live prices while the market is open. Can be late or missed if the feed or server is down. Information only.</p>
        </div>
      )}
    </div>
  );
}
