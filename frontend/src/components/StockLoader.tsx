import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiGet, apiPost } from "@/lib/api";

interface LoaderStatus {
  phase: "idle" | "list" | "history" | "done" | "stopped" | "error";
  message: string;
  total: number;
  done: number;
  saved: number;
  failed: number;
  running: boolean;
  stop_requested: boolean;
  token_set: boolean;
  directory: { total: number; loaded: boolean; updated_at: string | null };
  history_stocks: number;
}

function problem(error: unknown) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
  }
  return "That didn't work. Try again.";
}

// Owner only: load every NSE stock from Upstox into the app, from the server itself (no PC needed). Names first, then a year of daily candles.
export default function StockLoader() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [years, setYears] = useState(1);
  const status = useQuery({
    queryKey: ["stock-loader"],
    queryFn: () => apiGet<LoaderStatus>("/access/admin/stocks"),
    refetchInterval: (query) => (query.state.data?.running ? 3_000 : 30_000),
    retry: false,
  });
  const s = status.data;
  const act = async (path: string, body?: Record<string, unknown>) => {
    setError(null);
    try {
      await apiPost(path, body);
      await queryClient.invalidateQueries({ queryKey: ["stock-loader"] });
    } catch (e) {
      setError(problem(e));
    }
  };
  if (!s) return null;
  const estimate = Math.round(((s.directory.loaded ? s.directory.total : 2200) * 17 * years) / 1024); // about 17 KB per stock-year (measured)
  const percent = s.total > 0 ? Math.round((s.done / s.total) * 100) : 0;
  const button = "h-8 rounded-md border border-[#26334b] px-3 text-xs text-slate-200 hover:bg-[#1a2336] disabled:opacity-50";
  return (
    <section aria-labelledby="loader-title" data-testid="stock-loader">
      <h3 id="loader-title" className="text-sm font-semibold text-white">All NSE stocks</h3>
      <p className="mt-1 text-xs text-slate-500">
        {s.directory.loaded ? `${s.directory.total.toLocaleString("en-IN")} stocks are searchable` : "Only the live stocks are searchable so far"}; {s.history_stocks.toLocaleString("en-IN")} have daily history for charts. Loading runs on the server and can take 20 to 30 minutes. You can close this page. It stops by itself if the database gets 75% full.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" data-testid="loader-list" disabled={s.running} onClick={() => void act("/access/admin/stocks/start", { kind: "list" })} className={button}>1. Load stock names</button>
        <select data-testid="loader-years" value={years} onChange={(e) => setYears(Number(e.target.value))} aria-label="How much daily history to load" disabled={s.running} className="h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300">
          <option value={0.5}>6 months</option>
          <option value={1}>1 year</option>
          <option value={2}>2 years</option>
        </select>
        <button type="button" data-testid="loader-history" disabled={s.running || !s.token_set} onClick={() => void act("/access/admin/stocks/start", { kind: "history", years })} className={button}>2. Load daily history</button>
        {s.running && <button type="button" data-testid="loader-stop" disabled={s.stop_requested} onClick={() => void act("/access/admin/stocks/stop")} className={button}>{s.stop_requested ? "Stopping…" : "Stop"}</button>}
      </div>
      <p data-testid="loader-estimate" className="mt-1.5 text-[11px] text-slate-500">Step 2 adds about {estimate} MB of the {s.directory.loaded ? "" : "estimated "}database for {years === 0.5 ? "6 months" : years === 1 ? "1 year" : "2 years"} of every stock. Check the Database space bar above first.</p>
      {!s.token_set && <p className="mt-2 text-[11px] leading-relaxed text-slate-500">Step 2 needs an Upstox token. In Render, open your backend, then Environment, and add <span className="font-mono">UPSTOX_ACCESS_TOKEN</span> (it expires every day, so make a fresh one the day you load). Never paste it anywhere else.</p>}
      {s.running && s.total > 0 && (
        <div className="mt-2" data-testid="loader-progress">
          <div className="h-2 overflow-hidden rounded-full bg-[#1a2336]" role="img" aria-label={`${s.done} of ${s.total} stocks done`}><div className="h-full bg-sky-400" style={{ width: `${Math.max(2, percent)}%` }} /></div>
          <p className="mt-1 text-[11px] text-slate-400">{s.done.toLocaleString("en-IN")} of {s.total.toLocaleString("en-IN")} stocks ({percent}%){s.failed > 0 ? `, ${s.failed} failed` : ""}</p>
        </div>
      )}
      {s.message && <p data-testid="loader-message" role="status" className={`mt-2 text-xs ${s.phase === "error" ? "text-rose-300" : "text-slate-300"}`}>{s.message}</p>}
      {error && <p role="alert" className="mt-2 text-xs text-rose-300">{error}</p>}
    </section>
  );
}
