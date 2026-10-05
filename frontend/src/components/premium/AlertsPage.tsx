import { useEffect } from "react";
import { Link } from "react-router-dom";

import { alertText, ago } from "@/lib/premium";
import { useAlertEvents, useAlerts } from "@/lib/premiumData";

// All your alerts and what has fired. Opening the page marks the notifications as read.
export default function AlertsPage() {
  const store = useAlerts();
  const feed = useAlertEvents();
  const { markRead, unread } = feed;
  useEffect(() => {
    if (unread > 0) markRead();
  }, [unread, markRead]);
  return (
    <div data-testid="alerts-page" className="space-y-4">
      <section className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-4">
        <h1 className="font-heading text-base text-slate-100">Notifications</h1>
        {feed.events.length === 0 ? <p className="mt-2 text-xs text-slate-500">Nothing has fired yet.</p> : (
          <ul data-testid="alert-events" className="mt-3 space-y-2">
            {feed.events.map((e, i) => (
              <li key={`${e.at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 text-xs">
                <Link to={`/premium/stocks/${encodeURIComponent(e.symbol)}`} className="text-sky-300 hover:underline">{e.message}</Link>
                <span className="text-[10px] text-slate-500">{ago(new Date(e.at * 1000).toISOString())}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-4">
        <h2 className="font-heading text-base text-slate-100">Your alerts ({store.alerts.length}/{store.max})</h2>
        {store.failed && <p className="mt-2 text-xs text-slate-500">Alerts couldn't be loaded right now.</p>}
        {!store.failed && store.alerts.length === 0 && <p className="mt-2 text-xs text-slate-500">None yet. Open any stock and press 🔔 Alert.</p>}
        <ul className="mt-3 space-y-2">
          {store.alerts.map((a) => (
            <li key={a.id} data-testid={`alert-row-${a.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <Link to={`/premium/stocks/${encodeURIComponent(a.symbol)}`} className="font-semibold text-slate-100 hover:underline">{a.symbol}</Link>
              <span className={a.active ? "text-slate-300" : "text-slate-500 line-through"}>{alertText(a)}</span>
              <span className="text-[10px] text-slate-500">{a.once ? "once" : "repeats"}{a.email ? " · email" : ""}{a.fired ? ` · fired ${a.fired}x` : ""}</span>
              <button type="button" onClick={() => void store.toggle({ id: a.id, active: !a.active })} className="ml-auto rounded px-2 py-0.5 text-sky-300 hover:bg-[#1a2336]">{a.active ? "Pause" : "Resume"}</button>
              <button type="button" aria-label="Delete alert" onClick={() => void store.remove(a.id)} className="rounded px-2 py-0.5 text-slate-500 hover:text-rose-300">Delete</button>
            </li>
          ))}
        </ul>
        <p className="mt-3 border-t border-[#202b42] pt-2 text-[10px] leading-relaxed text-slate-600">{store.note ?? "Alerts are checked against live prices while the market is open. They can be late or missed. Information only, not advice."}</p>
      </section>
    </div>
  );
}
