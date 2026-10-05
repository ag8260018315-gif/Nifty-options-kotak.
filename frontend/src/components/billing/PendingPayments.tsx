import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "@/lib/api";
import { explain } from "@/lib/exchange";
import { inr, type PendingOrder } from "@/lib/billing";

interface Row extends PendingOrder {
  email: string;
  kind: string;
}

export const fetchOrders = () => apiGet<{ orders: Row[] }>("/billing/admin/orders");

// Owner only: purchases waiting for money. Confirming one turns it into the plan the buyer agreed to; the amount must match exactly.
export default function PendingPayments() {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["billing-orders"], queryFn: fetchOrders, retry: false, refetchInterval: 60_000 });
  const [refs, setRefs] = useState<Record<string, string>>({});
  const done = (result: { orders: Row[] }) => {
    client.setQueryData(["billing-orders"], result);
    void client.invalidateQueries({ queryKey: ["access-premium"] });
  };
  const confirm = useMutation({ mutationFn: (o: Row) => apiPost<{ orders: Row[] }>(`/billing/admin/orders/${o.id}/confirm`, { reference: refs[o.id] ?? "", amount: o.amount }), onSuccess: done });
  const decline = useMutation({ mutationFn: (o: Row) => apiPost<{ orders: Row[] }>(`/billing/admin/orders/${o.id}/decline`), onSuccess: done });
  const rows = list.data?.orders ?? [];
  return (
    <section aria-labelledby="payments-title" data-testid="payments-admin">
      <h3 id="payments-title" className="text-sm font-semibold text-white">Payments waiting ({rows.length})</h3>
      <p className="mt-1 text-xs text-slate-500">Someone agreed to a plan. When the money reaches you, enter the UPI transaction id and confirm. The amount must match.</p>
      <ul className="mt-2 divide-y divide-[#1e2638] rounded-md border border-[#202b42]">
        {rows.map((o) => (
          <li key={o.id} data-testid="payment-row" className="space-y-2 px-3 py-2">
            <p className="text-xs text-slate-200">{o.email} · {o.plan === "premium" ? (o.kind === "premium_intro" ? "Premium (first month free)" : "Premium") : "Standard"} · <span className="font-semibold text-amber-300">{inr(o.amount)}</span> · <span className="font-mono text-slate-400">{o.code}</span></p>
            <div className="flex flex-wrap gap-2">
              <input data-testid="payment-ref" value={refs[o.id] ?? ""} onChange={(e) => setRefs({ ...refs, [o.id]: e.target.value })} placeholder="UPI transaction id" aria-label="Payment reference" className="h-8 min-w-0 flex-1 rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 text-xs text-slate-200 placeholder:text-slate-600" />
              <button type="button" data-testid="payment-confirm" disabled={confirm.isPending || (refs[o.id] ?? "").trim().length < 4} onClick={() => confirm.mutate(o)} className="h-8 rounded-md bg-emerald-400 px-3 text-xs font-semibold text-[#06140d] disabled:opacity-50">Money received</button>
              <button type="button" disabled={decline.isPending} onClick={() => decline.mutate(o)} className="h-8 rounded-md border border-[#26334b] px-3 text-xs text-slate-300 hover:bg-[#1a2336]">Decline</button>
            </div>
          </li>
        ))}
        {rows.length === 0 && <li className="px-3 py-2.5 text-xs text-slate-500">{list.isLoading ? "Loading…" : "Nothing waiting."}</li>}
      </ul>
      {(confirm.error || decline.error) && <p role="alert" className="mt-2 text-xs text-rose-300">{explain(confirm.error ?? decline.error)}</p>}
    </section>
  );
}
