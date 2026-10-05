import { useState } from "react";
import { Link } from "react-router-dom";
import { Activity } from "lucide-react";

import ListingForm from "@/components/exchange/ListingForm";
import {
  explain, STATUS_TEXT, useEnquire, useExchangeMeta, useListings, useMyListings, useProfile, useQueue, useReport, useSendMessage, useThread, useThreads, when,
  type ExchangeMeta, type Listing,
} from "@/lib/exchange";

type Tab = "browse" | "mine" | "messages" | "review";
const field = "rounded-md border border-[#26334b] bg-[#0b1019] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50";
const ghost = "rounded-md border border-[#26334b] px-3 py-1.5 text-xs text-slate-300 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50";

function Err({ error, id }: { error: unknown; id: string }) {
  return error ? <p data-testid={id} role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{explain(error)}</p> : null;
}

function DisplayName({ meta }: { meta: ExchangeMeta }) {
  const save = useProfile();
  const [name, setName] = useState("");
  const [editing, setEditing] = useState(false);
  if (meta.display_name && !editing) {
    return <p className="text-xs text-slate-500">You appear as <span data-testid="my-name" className="font-semibold text-slate-200">{meta.display_name}</span>. Your email is never shown. <button type="button" onClick={() => { setName(meta.display_name ?? ""); setEditing(true); }} className="underline">Change</button></p>;
  }
  return (
    <form data-testid="name-form" onSubmit={(e) => { e.preventDefault(); save.mutate(name, { onSuccess: () => setEditing(false) }); }} className="space-y-2 rounded-lg border border-amber-300/25 bg-amber-300/[0.06] p-3">
      <p className="text-xs text-amber-100">Pick a display name. It is what other members see instead of your email.</p>
      <div className="flex flex-wrap gap-2">
        <input data-testid="name-input" className={field} value={name} maxLength={24} onChange={(e) => setName(e.target.value)} placeholder="Display name" />
        <button type="submit" data-testid="name-save" disabled={save.isPending} className="rounded-md bg-amber-300 px-4 py-2 text-xs font-semibold text-[#1a1203] disabled:opacity-50">Save</button>
      </div>
      <Err error={save.error} id="name-error" />
    </form>
  );
}

function ListingCard({ listing, canAct }: { listing: Listing; canAct: boolean }) {
  const [mode, setMode] = useState<"" | "ask" | "report">("");
  const [text, setText] = useState("");
  const enquire = useEnquire();
  const report = useReport();
  const [done, setDone] = useState<string | null>(null);
  return (
    <li data-testid="listing-card" className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p data-testid="listing-title" className="text-sm font-semibold text-white">{listing.title}</p>
          <p className="mt-0.5 text-[11px] text-slate-500">{listing.category_label} · by {listing.seller_name}</p>
        </div>
        {listing.price_text && <span className="rounded-md border border-[#2a364f] px-2 py-0.5 text-[11px] text-slate-300">{listing.price_text}</span>}
      </div>
      <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-slate-300">{listing.description}</p>
      {done && <p data-testid="listing-done" className="mt-3 text-xs text-emerald-300">{done}</p>}
      {canAct && !listing.mine && !done && (
        <div className="mt-3 flex gap-2">
          <button type="button" data-testid="listing-enquire" onClick={() => setMode(mode === "ask" ? "" : "ask")} className="rounded-md bg-amber-300 px-3 py-1.5 text-xs font-semibold text-[#1a1203]">Send an enquiry</button>
          <button type="button" data-testid="listing-report" onClick={() => setMode(mode === "report" ? "" : "report")} className={ghost}>Report</button>
        </div>
      )}
      {listing.mine && <p className="mt-3 text-[11px] text-slate-500">This is your listing.</p>}
      {mode && !done && (
        <form
          className="mt-3 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (mode === "ask") enquire.mutate({ id: listing.id, message: text }, { onSuccess: () => { setDone("Sent. Replies appear under Messages."); setText(""); } });
            else report.mutate({ id: listing.id, reason: text }, { onSuccess: (r) => { setDone(r.message); setText(""); } });
          }}
        >
          <textarea data-testid="listing-text" className={`${field} min-h-20 w-full`} value={text} maxLength={600} onChange={(e) => setText(e.target.value)} placeholder={mode === "ask" ? "Ask the seller about the service…" : "What is wrong with this listing?"} />
          <button type="submit" data-testid="listing-send" disabled={enquire.isPending || report.isPending} className={ghost}>{mode === "ask" ? "Send" : "Send report"}</button>
          <Err error={mode === "ask" ? enquire.error : report.error} id="listing-error" />
        </form>
      )}
    </li>
  );
}

function Browse({ meta }: { meta: ExchangeMeta }) {
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const list = useListings(category, q);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <input data-testid="ex-search" className={`${field} min-w-52 flex-1`} value={q} maxLength={60} onChange={(e) => setQ(e.target.value)} placeholder="Search services" />
        <select data-testid="ex-category" className={field} value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {Object.entries(meta.categories).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      {list.isPending && <p className="text-xs text-slate-500">Loading…</p>}
      {list.isError && <p className="text-xs text-slate-500">Couldn't load listings right now.</p>}
      {list.data && list.data.listings.length === 0 && <p data-testid="ex-empty" className="rounded-lg border border-[#202b42] p-4 text-sm text-slate-400">No services listed yet{q || category ? " for that search" : ""}. Be the first: add a listing under My listings.</p>}
      <ul className="grid gap-3 md:grid-cols-2">{list.data?.listings.map((l) => <ListingCard key={l.id} listing={l} canAct={!!meta.display_name} />)}</ul>
      {!meta.display_name && <p className="text-xs text-slate-500">Choose a display name above to send enquiries.</p>}
    </div>
  );
}

function Mine({ meta }: { meta: ExchangeMeta }) {
  const store = useMyListings();
  const [form, setForm] = useState<"" | "new" | string>("");
  const editing = store.listings.find((l) => l.id === form);
  return (
    <div className="space-y-3">
      {!form && <button type="button" data-testid="new-listing" disabled={!meta.display_name} onClick={() => setForm("new")} className="rounded-md bg-amber-300 px-4 py-2 text-xs font-semibold text-[#1a1203] disabled:opacity-40">+ New listing</button>}
      {!meta.display_name && <p className="text-xs text-slate-500">Choose a display name first.</p>}
      {form === "new" && <ListingForm categories={meta.categories} rules={meta.rules} onCancel={() => setForm("")} onSubmit={async (f) => { await store.create.mutateAsync(f); setForm(""); }} />}
      {editing && <ListingForm categories={meta.categories} rules={meta.rules} initial={editing} onCancel={() => setForm("")} onSubmit={async (f) => { await store.edit.mutateAsync({ id: editing.id, form: f }); setForm(""); }} />}
      {store.listings.length === 0 && !store.loading && <p className="text-sm text-slate-400">You haven't listed anything yet.</p>}
      <ul className="space-y-3">
        {store.listings.map((l) => (
          <li key={l.id} data-testid="my-listing" className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-4">
            <p className="text-sm font-semibold text-white">{l.title}</p>
            <p data-testid="my-status" className="mt-1 text-[11px] text-amber-200">{l.status ? STATUS_TEXT[l.status] : ""}{l.note ? ` — ${l.note}` : ""}</p>
            <p className="mt-2 line-clamp-2 text-xs text-slate-400">{l.description}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={ghost} onClick={() => setForm(l.id)}>Edit</button>
              {(l.status === "approved" || l.status === "paused") && <button type="button" className={ghost} onClick={() => store.pause.mutate({ id: l.id, paused: l.status === "approved" })}>{l.status === "approved" ? "Pause" : "Resume"}</button>}
              <button type="button" data-testid="my-delete" className={ghost} onClick={() => { if (window.confirm("Delete this listing?")) store.remove.mutate(l.id); }}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
      <Err error={store.pause.error ?? store.remove.error} id="mine-error" />
    </div>
  );
}

function Conversation({ id, onBack }: { id: string; onBack: () => void }) {
  const thread = useThread(id);
  const send = useSendMessage();
  const [text, setText] = useState("");
  const t = thread.data?.thread;
  return (
    <div data-testid="conversation" className="space-y-3">
      <button type="button" onClick={onBack} className={ghost}>← All conversations</button>
      {thread.isPending && <p className="text-xs text-slate-500">Loading…</p>}
      {t && (
        <>
          <p className="text-sm font-semibold text-white">{t.listing_title} <span className="text-xs font-normal text-slate-500">· with {t.other_name}</span></p>
          <ul className="space-y-2">
            {t.messages.map((m, i) => (
              <li key={i} className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed ${m.mine ? "ml-auto bg-amber-300/15 text-amber-50" : "bg-[#141b2b] text-slate-200"}`}>
                <p className="whitespace-pre-line">{m.text}</p>
                <p className="mt-1 text-[10px] text-slate-500">{m.mine ? "You" : t.other_name} · {when(m.at)}</p>
              </li>
            ))}
          </ul>
          <form onSubmit={(e) => { e.preventDefault(); send.mutate({ id, message: text }, { onSuccess: () => setText("") }); }} className="flex gap-2">
            <input data-testid="reply-input" className={`${field} flex-1`} value={text} maxLength={600} onChange={(e) => setText(e.target.value)} placeholder="Write a reply" />
            <button type="submit" data-testid="reply-send" disabled={send.isPending} className="rounded-md bg-amber-300 px-4 py-2 text-xs font-semibold text-[#1a1203] disabled:opacity-50">Send</button>
          </form>
          <Err error={send.error} id="reply-error" />
        </>
      )}
    </div>
  );
}

function Messages() {
  const threads = useThreads();
  const [open, setOpen] = useState<string | null>(null);
  if (open) return <Conversation id={open} onBack={() => setOpen(null)} />;
  const rows = threads.data?.threads ?? [];
  return (
    <div className="space-y-2">
      {threads.isPending && <p className="text-xs text-slate-500">Loading…</p>}
      {threads.data && rows.length === 0 && <p className="text-sm text-slate-400">No conversations yet. Send an enquiry from a listing, or wait for one on yours.</p>}
      <ul className="space-y-2">
        {rows.map((t) => (
          <li key={t.id}>
            <button type="button" data-testid="thread-row" onClick={() => setOpen(t.id)} className="flex w-full items-start justify-between gap-3 rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-3 text-left hover:bg-[#121a2a]">
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-white">{t.listing_title}</span>
                <span className="block truncate text-[11px] text-slate-500">{t.role === "seller" ? "Enquiry from" : "Seller"} {t.other_name} · {t.messages[0]?.text}</span>
              </span>
              {t.unread > 0 && <span data-testid="thread-unread" className="rounded-full bg-rose-500 px-1.5 text-[10px] font-bold text-white">{t.unread}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Review() {
  const { queue, loading, decide } = useQueue(true);
  const Row = ({ l, reported }: { l: Listing; reported: boolean }) => (
    <li data-testid="review-row" className="rounded-lg border border-[#202b42] bg-[#0c0f17]/95 p-4">
      <p className="text-sm font-semibold text-white">{l.title} <span className="text-[11px] font-normal text-slate-500">· {l.category_label} · by {l.seller_name}</span></p>
      <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-slate-300">{l.description}</p>
      {l.price_text && <p className="mt-1 text-[11px] text-slate-500">Price note: {l.price_text}</p>}
      {reported && <ul className="mt-2 list-disc pl-4 text-[11px] text-amber-200">{(l.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" data-testid="review-approve" className="rounded-md bg-emerald-400 px-3 py-1.5 text-xs font-semibold text-[#06140d]" onClick={() => decide.mutate({ id: l.id, action: "approve" })}>{reported ? "Keep it live" : "Approve"}</button>
        {!reported && <button type="button" data-testid="review-reject" className={ghost} onClick={() => { const note = window.prompt("Tell the seller why (optional)") ?? undefined; decide.mutate({ id: l.id, action: "reject", note }); }}>Reject</button>}
        <button type="button" data-testid="review-remove" className={ghost} onClick={() => { if (window.confirm("Remove this listing for good?")) decide.mutate({ id: l.id, action: "remove" }); }}>Remove</button>
      </div>
    </li>
  );
  return (
    <div className="space-y-4">
      {loading && <p className="text-xs text-slate-500">Loading…</p>}
      <section>
        <p className="mb-2 text-xs font-semibold text-slate-300">Waiting for approval ({queue?.pending.length ?? 0})</p>
        <ul className="space-y-3">{queue?.pending.map((l) => <Row key={l.id} l={l} reported={false} />)}</ul>
        {queue && queue.pending.length === 0 && <p className="text-xs text-slate-500">Nothing waiting.</p>}
      </section>
      <section>
        <p className="mb-2 text-xs font-semibold text-slate-300">Reported by members ({queue?.reported.length ?? 0})</p>
        <ul className="space-y-3">{queue?.reported.map((l) => <Row key={l.id} l={l} reported />)}</ul>
        {queue && queue.reported.length === 0 && <p className="text-xs text-slate-500">No reports.</p>}
      </section>
      <Err error={decide.error} id="review-error" />
    </div>
  );
}

export default function Exchange() {
  const metaQuery = useExchangeMeta();
  const [tab, setTab] = useState<Tab>("browse");
  const meta = metaQuery.data;
  const tabs: [Tab, string][] = [["browse", "Browse"], ["mine", "My listings"], ["messages", "Messages"], ...(meta?.is_owner ? [["review", "Review"] as [Tab, string]] : [])];
  return (
    <div data-testid="exchange-shell" className="min-h-svh bg-[#07090e] text-slate-100">
      <header className="sticky top-0 z-30 border-b border-amber-400/20 bg-[#0b0d12]/92 px-4 py-3 backdrop-blur-xl sm:px-6">
        <div className="mx-auto flex max-w-[1100px] flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-amber-300 text-[#1a1203]"><Activity className="size-5" /></div>
            <div>
              <p className="font-heading text-sm font-semibold tracking-wide text-white">TRADER'S EXCHANGE</p>
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Services notice board · no payments</p>
            </div>
          </div>
          <Link to="/" className={ghost}>← Options desk</Link>
        </div>
      </header>
      <main className="mx-auto max-w-[1100px] space-y-4 px-4 py-5 pb-24 sm:px-6">
        {metaQuery.isError && <p className="text-sm text-slate-400">The Exchange isn't available right now.</p>}
        {meta && (
          <>
            <p data-testid="ex-note" className="rounded-lg border border-[#202b42] p-3 text-[11px] leading-relaxed text-slate-400">{meta.note}</p>
            <DisplayName meta={meta} />
            <nav aria-label="Exchange sections" className="flex flex-wrap items-center gap-1 rounded-lg border border-[#202b42] bg-[#0e131d] p-1">
              {tabs.map(([id, label]) => (
                <button key={id} type="button" data-testid={`ex-tab-${id}`} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)} className={`rounded-md px-3.5 py-2 text-xs font-semibold ${tab === id ? "bg-amber-300 text-[#1a1203]" : "text-slate-400 hover:text-slate-200"}`}>
                  {label}
                  {id === "messages" && meta.unread > 0 && <span data-testid="ex-unread" className="ml-1.5 rounded-full bg-rose-500 px-1.5 text-[10px] font-bold text-white">{meta.unread}</span>}
                  {id === "review" && (meta.pending ?? 0) > 0 && <span data-testid="ex-pending" className="ml-1.5 rounded-full bg-rose-500 px-1.5 text-[10px] font-bold text-white">{meta.pending}</span>}
                </button>
              ))}
            </nav>
            {tab === "browse" && <Browse meta={meta} />}
            {tab === "mine" && <Mine meta={meta} />}
            {tab === "messages" && <Messages />}
            {tab === "review" && meta.is_owner && <Review />}
          </>
        )}
      </main>
    </div>
  );
}
