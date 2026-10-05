import { useState } from "react";

import { explain, type Listing, type ListingForm as Form } from "@/lib/exchange";

const input = "w-full rounded-md border border-[#26334b] bg-[#0b1019] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50";

// Create or edit a listing. The server checks the wording again; this form only helps people get it right the first time.
export default function ListingForm({ categories, rules, initial, onSubmit, onCancel }: {
  categories: Record<string, string>;
  rules: string[];
  initial?: Listing;
  onSubmit: (form: Form) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>({ title: initial?.title ?? "", category: initial?.category ?? "", description: initial?.description ?? "", price_text: initial?.price_text ?? "", accept: false });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSubmit(form);
    } catch (e) {
      setError(explain(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form data-testid="listing-form" onSubmit={(e) => { e.preventDefault(); void submit(); }} className="space-y-3 rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-4">
      <p className="text-sm font-semibold text-slate-200">{initial ? "Edit your listing" : "New listing"}</p>
      <div className="rounded-md border border-amber-300/25 bg-amber-300/[0.06] p-3 text-[11px] leading-relaxed text-amber-100/90">
        <p className="font-semibold">Before you post</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-4">{rules.map((r) => <li key={r}>{r}</li>)}</ul>
      </div>
      <label className="block text-xs text-slate-400">Title
        <input data-testid="lf-title" className={`${input} mt-1`} value={form.title} maxLength={80} onChange={(e) => set("title", e.target.value)} placeholder="e.g. Options basics: a recorded course" />
      </label>
      <label className="block text-xs text-slate-400">Category
        <select data-testid="lf-category" className={`${input} mt-1`} value={form.category} onChange={(e) => set("category", e.target.value)}>
          <option value="">Choose…</option>
          {Object.entries(categories).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <label className="block text-xs text-slate-400">What you offer
        <textarea data-testid="lf-description" className={`${input} mt-1 min-h-28`} value={form.description} maxLength={1000} onChange={(e) => set("description", e.target.value)} placeholder="Describe the service, who it is for and what they get. Education and tools only." />
        <span className="mt-1 block text-right text-[10px] text-slate-600">{form.description.length}/1000</span>
      </label>
      <label className="block text-xs text-slate-400">Price note (optional, text only)
        <input data-testid="lf-price" className={`${input} mt-1`} value={form.price_text} maxLength={40} onChange={(e) => set("price_text", e.target.value)} placeholder="e.g. ₹999 per month, or Free" />
      </label>
      <label className="flex items-start gap-2 text-xs leading-relaxed text-slate-300">
        <input data-testid="lf-accept" type="checkbox" className="mt-0.5" checked={form.accept} onChange={(e) => set("accept", e.target.checked)} />
        <span>I confirm this is a service listing that follows the rules above. It does not offer trading tips, calls, signals, investment advice, portfolio management or any promised return, and I understand the owner can remove it at any time.</span>
      </label>
      {error && <p data-testid="lf-error" role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" data-testid="lf-submit" disabled={busy} className="rounded-md bg-amber-300 px-4 py-2 text-xs font-semibold text-[#1a1203] disabled:opacity-50">{busy ? "Sending…" : initial ? "Save and send for approval" : "Send for approval"}</button>
        <button type="button" onClick={onCancel} className="rounded-md border border-[#26334b] px-4 py-2 text-xs text-slate-300 hover:bg-[#1a2336]">Cancel</button>
      </div>
    </form>
  );
}
