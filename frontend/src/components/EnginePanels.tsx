import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiGet } from "@/lib/api";

// Two separate sections that must never be confused:
//   LIVE SIGNAL                       -> current data only (/api/live/*)
//   RESEARCH / HISTORICAL ANALYSIS    -> past data only   (/api/research/*)
// "Current signal confidence" and "Historical validated accuracy" are different numbers and are never merged.

type IndexSymbol = "NIFTY" | "BANKNIFTY" | "FINNIFTY";

interface HistoricalValidation {
  validated: boolean;
  accuracy_pct: number | null;
  signals: number | null;
  period: [string, string] | null;
  method: string | null;
  measured_on: string | null;
  label: string;
  generated_by: string;
}

interface StrikePick {
  strike: number;
  type: "CE" | "PE";
  premium: number;
  delta: number;
  iv: number;
  oi: number;
  score: number;
  is_atm: boolean;
}

interface LiveSignal {
  label: string;
  symbol: string;
  as_of: string;
  action: "BUY CE" | "BUY PE" | "NO SIGNAL";
  confidence: number;
  confidence_label: string;
  simulated: boolean;
  strike: StrikePick | null;
  risk: { entry_premium: number; premium_stop: number; premium_target: number; reward_risk: number; index_stop: number | null; index_stop_points: number | null } | null;
  components: Record<string, number | null>;
  reasons: string[];
  historical_validation: HistoricalValidation;
  data_status: { feed_state: string; ok: boolean; candles_used: number; candles_required: number; violations: { code: string; detail: string }[] };
  disclaimer?: string;
}

interface Fold {
  train: [string, string];
  test: [string, string];
  out_of_sample: { signals: number; accuracy_pct: number | null };
  in_sample: { signals: number; accuracy_pct: number | null };
}

interface ResearchRun {
  run_id: string;
  created_at: string;
  status: string;
  days: number;
  period: [string, string] | null;
  horizon_bars: number;
  note: string;
  folds: Fold[];
  leakage_check: { passed: boolean; detail: string } | null;
  calibration: { band: string; signals: number; hit_rate_pct: number | null }[];
  oos?: { signals: number; accuracy_pct: number | null; expectancy_pts: number | null };
}

interface ResearchSummary {
  label: string;
  latest_run: ResearchRun | null;
  active_config_validation: { accuracy_pct: number; signals: number; period_start: string; period_end: string; horizon_bars: number; measured_on: string } | null;
  active_config_generated_by: string;
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(1)}%`);

function Banner({ tone, title, text, testId }: { tone: "live" | "research"; title: string; text: string; testId: string }) {
  const cls = tone === "live" ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-300" : "border-violet-500/30 bg-violet-500/5 text-violet-300";
  return (
    <div data-testid={testId} className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-4 py-2 ${cls}`}>
      <span className="text-xs font-bold uppercase tracking-[0.2em]">{title}</span>
      <span className="text-[11px] opacity-80">{text}</span>
    </div>
  );
}

function Brief({ tone, summary, points, testId }: { tone: "live" | "research"; summary: string; points: string[]; testId: string }) {
  const accent = tone === "live" ? "text-emerald-300" : "text-violet-300";
  return (
    <details data-testid={testId} className="group rounded-lg border border-[#202b42] bg-[#0e131d]/90 px-4 py-2.5">
      <summary className="cursor-pointer list-none text-xs text-slate-300">
        <span className={`mr-2 font-semibold ${accent}`}>How this works</span>
        <span className="text-slate-500">{summary}</span>
      </summary>
      <ul className="mt-2 space-y-1.5 border-t border-[#202b42] pt-2">
        {points.map((point) => <li key={point} className="text-[11px] leading-relaxed text-slate-400">• {point}</li>)}
      </ul>
    </details>
  );
}

export function LiveSignalPanel({ symbol }: { symbol: IndexSymbol }) {
  const query = useQuery({ queryKey: ["live-signal", symbol], queryFn: () => apiGet<LiveSignal>(`/live/signal?symbol=${symbol}`), refetchInterval: 3000, retry: false });
  const s = query.data;
  const hv = s?.historical_validation;
  const actionable = s && s.action !== "NO SIGNAL";
  const box = "rounded-md border border-[#202b42] bg-[#090d15] px-3 py-2";
  return (
    <section id="signals" aria-label="Live signal" className="scroll-mt-4 space-y-3">
      <Banner tone="live" title="Live signal" text="Computed from current market data only. Not a backtest." testId="live-signal-banner" />
      <Brief
        tone="live"
        testId="live-signal-brief"
        summary="A signal built only from the market right now."
        points={[
          "Checks the live feed first. Stale, future-dated, or unfinished data blocks the signal.",
          "Reads trend (EMA), momentum (RSI) and open interest (PCR), then picks the best-scoring strike.",
          "Current signal confidence is how strong the setup is right now. It is not a win rate.",
          "Historical validated accuracy comes from the Research section below. It is a separate number and is only shown after research has validated it.",
          "Stop and target levels are shown for the chosen strike. The app never places orders.",
        ]}
      />
      <Card data-testid="live-signal-card" className="border-[#202b42] bg-[#0c0f17]/95">
        <CardHeader className="flex-row items-center justify-between border-b border-[#202b42] px-4 py-3">
          <CardTitle className="font-heading text-base text-slate-100">{symbol} current signal</CardTitle>
          <div className="flex gap-2">
            {s?.simulated && <Badge data-testid="live-signal-simulated" className="border-indigo-500/30 bg-indigo-500/10 text-[10px] text-indigo-300">SIMULATED DEMO DATA</Badge>}
            <Badge data-testid="live-data-status" className={`text-[10px] ${s?.data_status.ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300"}`}>
              DATA {s?.data_status.ok ? "OK" : "BLOCKED"} · {s?.data_status.feed_state ?? "…"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 p-4">
          {query.isError && <p data-testid="live-signal-error" className="text-xs text-slate-500">The live signal is unavailable right now.</p>}
          {s && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className={box}><p className="text-[10px] text-slate-500">Current signal</p><p data-testid="live-signal-action" className={`mt-1 font-mono text-lg font-bold ${s.action === "BUY CE" ? "text-emerald-300" : s.action === "BUY PE" ? "text-rose-300" : "text-slate-300"}`}>{s.action}</p></div>
                <div className={box}><p className="text-[10px] text-slate-500">Selected strike</p><p data-testid="live-signal-strike" className="mt-1 font-mono text-lg font-bold text-slate-100">{s.strike ? `${s.strike.strike} ${s.strike.type}` : "—"}</p><p className="text-[10px] text-slate-500">{s.strike ? `premium ${s.strike.premium} · delta ${s.strike.delta}` : "no strike selected"}</p></div>
                <div className={box}><p className="text-[10px] text-slate-500">Current signal confidence</p><p data-testid="live-signal-confidence" className="mt-1 font-mono text-lg font-bold text-slate-100">{s.confidence}%</p><p className="text-[10px] text-slate-500">signal strength right now</p></div>
                <div className={box}><p className="text-[10px] text-slate-500">{hv?.label ?? "Historical validated accuracy"}</p><p data-testid="live-historical-accuracy" className="mt-1 font-mono text-lg font-bold text-violet-300">{hv?.validated ? pct(hv.accuracy_pct) : "Not validated"}</p><p className="text-[10px] text-slate-500">{hv?.validated ? `from research · ${hv.signals} out-of-sample signals` : "run the research engine"}</p></div>
              </div>
              {actionable && s.risk && (
                <div data-testid="live-signal-risk" className="grid gap-3 sm:grid-cols-4">
                  <div className={box}><p className="text-[10px] text-slate-500">Entry premium</p><p className="mt-1 font-mono text-sm text-slate-100">{s.risk.entry_premium}</p></div>
                  <div className={box}><p className="text-[10px] text-slate-500">Premium stop</p><p className="mt-1 font-mono text-sm text-rose-300">{s.risk.premium_stop}</p></div>
                  <div className={box}><p className="text-[10px] text-slate-500">Premium target</p><p className="mt-1 font-mono text-sm text-emerald-300">{s.risk.premium_target}</p></div>
                  <div className={box}><p className="text-[10px] text-slate-500">Index stop</p><p className="mt-1 font-mono text-sm text-slate-100">{s.risk.index_stop ?? "—"}</p></div>
                </div>
              )}
              <ul data-testid="live-signal-reasons" className="space-y-1.5">{s.reasons.map((r) => <li key={r} className="text-xs text-slate-400">• {r}</li>)}</ul>
              <p className="text-[10px] text-slate-600">Data as of {new Date(s.as_of).toLocaleTimeString("en-IN")} · candles {s.data_status.candles_used}/{s.data_status.candles_required} · {s.disclaimer ?? "Informational only. The app never places orders."}</p>
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

export function ResearchPanel({ symbol }: { symbol: IndexSymbol }) {
  const query = useQuery({ queryKey: ["research-summary", symbol], queryFn: () => apiGet<ResearchSummary>(`/research/summary?symbol=${symbol}`), refetchInterval: 60000, retry: false });
  const run = query.data?.latest_run;
  const active = query.data?.active_config_validation;
  const box = "rounded-md border border-[#202b42] bg-[#090d15] px-3 py-2";
  return (
    <section id="research" aria-label="Research and historical analysis" className="scroll-mt-4 space-y-3">
      <Banner tone="research" title="Research / historical analysis" text="Past data only. These numbers are not live signals." testId="research-banner" />
      <Brief
        tone="research"
        testId="research-brief"
        summary="Past data used to tune and test the settings. It never creates a live trade."
        points={[
          "Research runs on historical candles only and tests the rules on sessions it did not tune on (walk-forward).",
          "Accuracy here is index-direction accuracy at a fixed horizon, not option profit or a promise of live results.",
          "A look-ahead check confirms no future data was used. If it fails, no settings are written.",
          "The only thing research passes to the live engine is a settings file (config.json). Nothing else is shared.",
          "Until a research run is applied, the dashboard says Not validated and the live engine uses default settings.",
        ]}
      />
      <Card data-testid="research-card" className="border-violet-500/15 bg-[#0c0f17]/95">
        <CardHeader className="border-b border-[#202b42] px-4 py-3"><CardTitle className="font-heading text-base text-slate-100">{symbol} historical validation</CardTitle></CardHeader>
        <CardContent className="space-y-4 p-4">
          {query.isError && <p className="text-xs text-slate-500">Research results are unavailable right now.</p>}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className={box}><p className="text-[10px] text-slate-500">Historical validated accuracy</p><p data-testid="research-accuracy" className="mt-1 font-mono text-lg font-bold text-violet-300">{active ? pct(active.accuracy_pct) : "Not validated"}</p><p className="text-[10px] text-slate-500">{active ? `${active.signals} out-of-sample signals · ${active.period_start} → ${active.period_end}` : "no research run applied yet"}</p></div>
            <div className={box}><p className="text-[10px] text-slate-500">Latest research run</p><p data-testid="research-status" className="mt-1 font-mono text-sm text-slate-200">{run ? run.status : "none"}</p><p className="text-[10px] text-slate-500">{run ? `${run.days} sessions · horizon ${run.horizon_bars} bars` : "—"}</p></div>
            <div className={box}><p className="text-[10px] text-slate-500">Look-ahead check</p><p data-testid="research-leakage" className="mt-1 font-mono text-sm text-slate-200">{run?.leakage_check ? (run.leakage_check.passed ? "PASSED" : "FAILED") : "—"}</p><p className="text-[10px] text-slate-500">{run?.leakage_check?.detail ?? ""}</p></div>
          </div>
          {run && run.folds.length > 0 && (
            <div data-testid="research-folds" className="overflow-x-auto">
              <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Walk-forward folds (test sessions were never used to pick parameters)</p>
              <table className="w-full text-left text-xs text-slate-400"><thead><tr className="text-[10px] text-slate-500"><th className="py-1">Train</th><th>Test</th><th>In-sample</th><th>Out-of-sample</th></tr></thead>
                <tbody>{run.folds.map((f) => <tr key={f.test[0]} className="border-t border-[#202b42]"><td className="py-1">{f.train[0]} → {f.train[1]}</td><td>{f.test[0]} → {f.test[1]}</td><td>{pct(f.in_sample.accuracy_pct)} ({f.in_sample.signals})</td><td>{pct(f.out_of_sample.accuracy_pct)} ({f.out_of_sample.signals})</td></tr>)}</tbody></table>
            </div>
          )}
          {run && run.calibration.length > 0 && (
            <div data-testid="research-calibration" className="flex flex-wrap gap-2">
              {run.calibration.filter((c) => c.signals > 0).map((c) => <span key={c.band} className="rounded border border-[#202b42] px-2 py-1 text-[10px] text-slate-400">confidence {c.band}: hit {pct(c.hit_rate_pct)} ({c.signals})</span>)}
            </div>
          )}
          <p className="text-[10px] text-slate-600">{run?.note ?? "Accuracy is out-of-sample index-direction accuracy, never a promise of live results."}</p>
        </CardContent>
      </Card>
    </section>
  );
}
