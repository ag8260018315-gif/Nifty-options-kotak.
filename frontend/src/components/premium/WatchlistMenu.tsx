import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { checkName } from "@/lib/premium";
import { FAVOURITES, useWatchlists } from "@/lib/premiumData";

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
  }
  return "That didn't go through. Try again shortly.";
}

// Add or remove one stock from any of the user's watchlists, or start a new list with it.
export default function WatchlistMenu({ symbol }: { symbol: string }) {
  const lists = useWatchlists();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const names = Array.from(new Set([FAVOURITES, ...Object.keys(lists.lists)])).sort((a, b) => (a === FAVOURITES ? -1 : b === FAVOURITES ? 1 : a.localeCompare(b)));
  const inAny = names.some((n) => lists.has(n, symbol));

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const create = async () => {
    const trimmed = name.trim();
    const bad = checkName(trimmed);
    if (bad) {
      setProblem(bad);
      return;
    }
    try {
      await lists.create(trimmed, [symbol]);
      setName("");
      setProblem(null);
    } catch (error) {
      setProblem(explain(error));
    }
  };

  return (
    <div className="relative">
      <button type="button" data-testid="watchlist-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)} className={`h-8 rounded-md border px-3 text-xs ${inAny ? "border-amber-300/50 bg-amber-300/10 text-amber-200" : "border-[#26334b] text-slate-300 hover:bg-[#1a2336]"}`}>{inAny ? "★" : "☆"} Watchlists ▾</button>
      {open && (
        <div data-testid="watchlist-panel" role="group" aria-label="Watchlists" className="absolute left-0 z-20 mt-1 w-64 max-w-[85vw] sm:left-auto sm:right-0 rounded-lg border border-[#2a364f] bg-[#0e131d] p-3 shadow-xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Add {symbol} to</p>
          {lists.failed && <p className="mt-2 text-[11px] text-rose-300">Watchlists couldn't be loaded right now.</p>}
          <ul className="mt-2 space-y-0.5">
            {names.map((listName) => (
              <li key={listName}>
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-slate-200 hover:bg-[#1a2336]">
                  <input type="checkbox" data-testid={`watchlist-check-${listName}`} checked={lists.has(listName, symbol)} disabled={!lists.ready} onChange={() => lists.toggle(listName, symbol)} className="size-3.5 accent-amber-300 disabled:opacity-50" />
                  <span className="min-w-0 flex-1 truncate">{listName}</span>
                  <span className="text-[10px] text-slate-500">{(lists.lists[listName] ?? []).length}</span>
                </label>
              </li>
            ))}
          </ul>
          <form className="mt-3 flex gap-2 border-t border-[#202b42] pt-3" onSubmit={(event) => { event.preventDefault(); void create(); }}>
            <input data-testid="watchlist-new-name" value={name} maxLength={30} onChange={(event) => setName(event.target.value)} placeholder="New list name" aria-label="New watchlist name" className="h-8 min-w-0 flex-1 rounded-md border border-[#2a364f] bg-[#0b0f17] px-2 text-xs text-slate-200 placeholder:text-slate-600" />
            <button type="submit" data-testid="watchlist-new-save" disabled={lists.saving || !lists.ready} className="h-8 rounded-md bg-amber-300 px-3 text-xs font-semibold text-[#1a1203] hover:bg-amber-200 disabled:opacity-60">Create</button>
          </form>
          <p className="mt-2 text-[10px] leading-snug text-slate-600">Up to {lists.maxLists} lists. They belong to your account and follow you across devices.</p>
          {(problem || lists.error) && <p role="alert" className="mt-1 text-[11px] text-rose-300">{problem ?? explain(lists.error)}</p>}
        </div>
      )}
    </div>
  );
}
