import { useState } from "react";

import { apiPost } from "@/lib/api";
import { explain } from "@/lib/exchange";

const LABELS: Record<string, string> = {
  premium_watchlists: "Watchlists", premium_layouts: "Chart layouts", "premium_alerts.owner": "Alerts", "premium_alert_events.owner": "Alert notifications",
  exchange_profiles: "Exchange profile", "exchange_listings.owner": "Exchange listings", "exchange_threads.buyer": "Conversations (as buyer)", "exchange_threads.seller": "Conversations (as seller)",
  billing_subscriptions: "Subscription", "billing_orders.email": "Pending orders",
};

// Owner only: bring one email's saved watchlists, layouts, alerts and Exchange items across to another email. Always previews first.
export default function MoveData() {
  const [oldEmail, setOld] = useState("");
  const [newEmail, setNew] = useState("");
  const [result, setResult] = useState<{ moved: boolean; report: Record<string, number> } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const run = async (apply: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setResult(await apiPost("/access/admin/move-data", { old: oldEmail, new: newEmail, apply }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const input = "h-8 min-w-0 flex-1 rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 text-xs text-slate-200 placeholder:text-slate-600";
  const items = Object.entries(result?.report ?? {});
  return (
    <section aria-labelledby="move-title" data-testid="move-data">
      <h3 id="move-title" className="text-sm font-semibold text-white">Move saved data to another email</h3>
      <p className="mt-1 text-xs text-slate-500">Brings watchlists, chart layouts, alerts and Exchange items from one email to another. Preview first. Nothing already on the new email is overwritten.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <input data-testid="move-old" value={oldEmail} onChange={(e) => { setOld(e.target.value); setResult(null); }} placeholder="From (old email)" aria-label="Old email" className={input} />
        <input data-testid="move-new" value={newEmail} onChange={(e) => { setNew(e.target.value); setResult(null); }} placeholder="To (new email)" aria-label="New email" className={input} />
      </div>
      <div className="mt-2 flex gap-2">
        <button type="button" data-testid="move-preview" disabled={busy || oldEmail.trim().length < 3 || newEmail.trim().length < 3} onClick={() => void run(false)} className="h-8 rounded-md border border-[#26334b] px-3 text-xs text-slate-200 hover:bg-[#1a2336] disabled:opacity-50">Preview</button>
        {result && !result.moved && items.length > 0 && <button type="button" data-testid="move-apply" disabled={busy} onClick={() => void run(true)} className="h-8 rounded-md bg-amber-300 px-3 text-xs font-semibold text-[#1a1203] disabled:opacity-50">Move it</button>}
      </div>
      {result && (
        <div data-testid="move-result" role="status" className="mt-2 rounded-md border border-[#202b42] px-3 py-2 text-xs text-slate-300">
          {items.length === 0 ? "Nothing found under the old email." : <>
            <p className="font-semibold">{result.moved ? "Moved:" : "Would move:"}</p>
            <ul className="mt-1 list-disc pl-4">{items.map(([k, n]) => <li key={k}>{LABELS[k] ?? k}: {n}</li>)}</ul>
          </>}
        </div>
      )}
      {error ? <p role="alert" className="mt-2 text-xs text-rose-300">{explain(error)}</p> : null}
    </section>
  );
}
