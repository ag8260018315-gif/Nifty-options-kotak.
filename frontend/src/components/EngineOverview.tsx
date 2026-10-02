import type { CSSProperties } from "react";
import { Activity, Check, Database, FlaskConical, Gauge, History, Lock, ShieldCheck, Target, Wifi } from "lucide-react";

// A plain-language, animated picture of what this dashboard does. Static text only: it reads no data, so it
// can never be mistaken for a live signal or a research result. Animations stop for people who prefer reduced motion.

const LIVE_STEPS = [
  { icon: Wifi, label: "Live data", hint: "Spot, option chain, volume" },
  { icon: ShieldCheck, label: "Data checks", hint: "Fresh? No future data?" },
  { icon: Activity, label: "Indicators", hint: "Trend (EMA) and momentum (RSI)" },
  { icon: Database, label: "Option chain", hint: "Open interest lean (PCR)" },
  { icon: Target, label: "Best strike", hint: "Delta, liquidity, premium" },
  { icon: Gauge, label: "Confidence", hint: "Strength of the setup now" },
  { icon: Check, label: "Risk gate", hint: "Stop, target, trading hours" },
];

const SAFETY = [
  { icon: ShieldCheck, title: "No future data", text: "Every signal uses only what was known at that second. Future candles or prices block it." },
  { icon: Database, title: "Two separate stores", text: "Research history and live signals are kept in different databases and never mixed." },
  { icon: History, title: "Replayable", text: "Each signal is saved with its inputs, so it can be recalculated and checked later." },
  { icon: Lock, title: "Read-only", text: "The dashboard never places orders. It informs; you decide." },
];

function Dots() {
  return (
    <div aria-hidden className="mx-3 hidden min-w-32 flex-1 flex-col items-center justify-center gap-1 md:flex">
      <span className="rounded-full border border-[#2a364f] bg-[#0e131d] px-2.5 py-0.5 text-[10px] text-slate-300">settings file</span>
      <div className="relative flex h-4 w-full items-center">
        <div className="h-px w-full bg-gradient-to-r from-violet-500/60 to-emerald-500/60" />
        <svg className="absolute right-0 size-3 text-emerald-400" viewBox="0 0 12 12" fill="currentColor"><path d="M2 1l9 5-9 5z" /></svg>
        {[0, 1, 2].map((i) => (
          <span key={i} className="eo-flow absolute left-0 size-1.5 rounded-full bg-sky-300" style={{ animationDelay: `${i * 0.8}s` }} />
        ))}
      </div>
      <span className="text-[9px] text-slate-500">Research to Live (settings only)</span>
    </div>
  );
}

export default function EngineOverview() {
  return (
    <section id="how" aria-label="How the engines work" data-testid="engine-overview" className="scroll-mt-4 space-y-4 rounded-xl border border-[#202b42] bg-[#0c0f17]/95 p-4">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-sky-300">How it works</p>
        <h2 data-testid="engine-overview-title" className="mt-1 font-heading text-lg text-slate-100">Two engines, kept apart</h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400">
          <span className="text-violet-300">Research</span> studies the past and decides the settings. <span className="text-emerald-300">Live</span> uses those settings on today's market to produce the signal you see. Research never makes a trade, and live never looks at the past results.
        </p>
      </div>

      <div className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
        <div className="eo-card flex-1 rounded-lg border border-violet-500/25 bg-violet-500/5 p-3" data-testid="overview-research">
          <div className="flex items-center gap-2 text-violet-300"><FlaskConical className="size-4" /><span className="text-xs font-bold uppercase tracking-widest">Research</span></div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">Past candles go in. The rules are tested on days they were not tuned on. The best settings and a look-ahead check come out.</p>
          <p className="mt-2 text-[10px] text-violet-300/80">Output: settings + a validated accuracy</p>
        </div>
        <Dots />
        <div className="eo-card flex-1 rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-3" data-testid="overview-live">
          <div className="flex items-center gap-2 text-emerald-300"><Wifi className="size-4" /><span className="text-xs font-bold uppercase tracking-widest">Live signal</span></div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">Current prices and option chain go in. Checks run, a strike is scored, and a signal with stop and target comes out.</p>
          <p className="mt-2 text-[10px] text-emerald-300/80">Output: signal + current confidence</p>
        </div>
      </div>

      <div data-testid="overview-pipeline">
        <p className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">Every live signal passes these steps</p>
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {LIVE_STEPS.map((step, i) => (
            <li key={step.label} className="eo-step rounded-lg border border-[#202b42] bg-[#090d15] p-2.5" style={{ animationDelay: `${i * 0.9}s` }}>
              <div className="flex items-center justify-between text-slate-300"><step.icon className="size-4" /><span className="font-mono text-[10px] text-slate-600">{i + 1}</span></div>
              <p className="mt-1.5 text-xs font-semibold text-slate-200">{step.label}</p>
              <p className="mt-0.5 text-[10px] leading-snug text-slate-500">{step.hint}</p>
            </li>
          ))}
        </ol>
      </div>

      <div data-testid="overview-numbers" className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-[#202b42] bg-[#090d15] p-3">
          <p className="text-[10px] text-slate-500">Current signal confidence <span className="text-slate-600">(example)</span></p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#141c2b]"><div className="eo-fill h-full rounded-full bg-emerald-400" style={{ "--w": "84%" } as CSSProperties} /></div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">How strong the setup looks right now. It changes every few seconds and is not a win rate.</p>
        </div>
        <div className="rounded-lg border border-[#202b42] bg-[#090d15] p-3">
          <p className="text-[10px] text-slate-500">Historical validated accuracy <span className="text-slate-600">(example)</span></p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#141c2b]"><div className="eo-fill h-full rounded-full bg-violet-400" style={{ "--w": "78%" } as CSSProperties} /></div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">How often the rules were right on past days they had not seen. Shown only after research has measured it. Never a promise.</p>
        </div>
      </div>

      <div data-testid="overview-safety" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SAFETY.map((item) => (
          <div key={item.title} className="eo-card rounded-lg border border-[#202b42] bg-[#090d15] p-3">
            <item.icon className="size-4 text-sky-300" />
            <p className="mt-1.5 text-xs font-semibold text-slate-200">{item.title}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{item.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
