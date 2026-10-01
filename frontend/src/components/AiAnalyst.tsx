import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Bot, FileText, MessageSquare, RefreshCw, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost, apiStream } from "@/lib/api";

// The numbers on the cards and in every answer come from the server's own data. The AI only writes the
// interpretation, and the server rejects any answer whose figures don't match the data.

type AiAction = "explain" | "chat" | "summary" | "alert";
type DeskSymbol = "NIFTY" | "BANKNIFTY" | "FINNIFTY";

interface InsightCard {
  id: string;
  title: string;
  data: { label: string; value: string }[];
  headline: string | null;
  shows: string | null;
  why: string | null;
  withheld: boolean;
}

interface CardsResult {
  symbol: string;
  generated_at: string;
  data_as_of: string | null;
  feed_state: string;
  note?: string | null;
  cards: InsightCard[];
}

interface CardsResponse {
  symbol: string;
  result: CardsResult | null;
}

interface Usage {
  used: number | null;
  limit: number | null;
  remaining: number | null;
}

// These must match the server's suggested questions exactly, so one answer is shared by everyone who asks.
const SUGGESTED_QUESTIONS = [
  "What is happening around the ATM strike?",
  "Where is open interest concentrated?",
  "Explain today's PCR.",
  "What changed in the option chain?",
  "Summarize the current market structure.",
  "Which strikes carry the heaviest positioning?",
];

const STALE_AFTER_MS = 180_000;

function clock(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

export function parseAnswer(text: string) {
  const markers = ["HEADLINE:", "DATA:", "INTERPRETATION:"] as const;
  const found = markers
    .map((marker) => ({ marker, at: text.indexOf(marker) }))
    .filter((item) => item.at >= 0)
    .sort((a, b) => a.at - b.at);
  const first = found[0];
  if (!first) return { lead: "", headline: "", data: "", interpretation: "", plain: text.trim() };
  const parts: Record<string, string> = {};
  found.forEach((item, index) => {
    const next = found[index + 1];
    parts[item.marker] = text.slice(item.at + item.marker.length, next ? next.at : text.length).trim();
  });
  return { lead: text.slice(0, first.at).trim(), headline: parts["HEADLINE:"] ?? "", data: parts["DATA:"] ?? "", interpretation: parts["INTERPRETATION:"] ?? "", plain: "" };
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    return "The AI analyst is temporarily unavailable. Try again shortly.";
  }
  if (error instanceof Error && error.message) return error.message;
  return "The AI analyst is temporarily unavailable. Try again shortly.";
}

function Chip({ label, tone }: { label: string; tone: "data" | "ai" }) {
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] ${tone === "data" ? "bg-slate-500/15 text-slate-300" : "bg-blue-500/15 text-blue-300"}`}>{label}</span>
  );
}

function InsightCardView({ card, dataAsOf, stale }: { card: InsightCard; dataAsOf: string | null; stale: boolean }) {
  return (
    <article data-testid={`insight-card-${card.id}`} className={`flex flex-col rounded-xl border border-[#202b42] bg-[#0c111b] p-4 transition-opacity ${stale ? "opacity-70" : ""}`}>
      <h4 className="font-heading text-sm font-semibold text-slate-100">{card.title}</h4>
      {card.headline && <p className="mt-0.5 text-xs text-slate-400">{card.headline}</p>}
      <div className="mt-3">
        <Chip tone="data" label="What the data shows" />
        <dl className="mt-2 space-y-1.5">
          {card.data.map((row) => (
            <div key={row.label} className="flex justify-between gap-3 text-xs">
              <dt className="text-slate-500">{row.label}</dt>
              <dd className="text-right font-mono tabular-nums text-slate-200">{row.value}</dd>
            </div>
          ))}
        </dl>
        {card.shows && <p className="mt-2 text-xs leading-relaxed text-slate-400">{card.shows}</p>}
      </div>
      <div className="mt-3 border-t border-[#1a2336] pt-3">
        <Chip tone="ai" label="Why it matters · AI interpretation" />
        <p data-testid={`insight-why-${card.id}`} className="mt-2 text-xs leading-relaxed text-slate-300">
          {card.why ?? "AI interpretation isn't available for this card right now. The figures above are still live data."}
        </p>
      </div>
      <p className="mt-auto pt-3 text-[10px] text-slate-600">Data as of {clock(dataAsOf)} IST</p>
    </article>
  );
}

export default function AiAnalyst({ symbol, configured, demo, dataAsOf, sessionId, onEnableNotifications }: { symbol: DeskSymbol; configured: boolean; demo: boolean; dataAsOf: string | null; sessionId: string; onEnableNotifications: () => void }) {
  const queryClient = useQueryClient();
  const [output, setOutput] = useState("");
  const [action, setAction] = useState<AiAction>("explain");
  const [contextAt, setContextAt] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [generated, setGenerated] = useState<Record<string, CardsResult>>({});
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, []);

  const usageQuery = useQuery({ queryKey: ["ai-usage"], queryFn: () => apiGet<Usage>("/ai/usage"), retry: false });
  const cachedCards = useQuery({ queryKey: ["ai-cards", symbol], queryFn: () => apiGet<CardsResponse>(`/ai/cards?symbol=${symbol}`), refetchInterval: 30_000, retry: false });
  const cards = generated[symbol] ?? cachedCards.data?.result ?? null;
  const cardsStale = cards ? now - Date.parse(cards.generated_at) > STALE_AFTER_MS : false;

  const cardsMutation = useMutation({
    mutationFn: () => apiPost<CardsResponse>("/ai/cards", { symbol }),
    onSuccess: (response: CardsResponse) => {
      if (response.result) setGenerated((current) => ({ ...current, [symbol]: response.result as CardsResult }));
    },
    onError: (error: unknown) => toast.error(errorMessage(error)),
  });

  const askMutation = useMutation({
    mutationFn: async ({ action: next, message }: { action: AiAction; message?: string }) => {
      let result = "";
      setAction(next);
      setOutput("");
      setProblem(null);
      setContextAt(dataAsOf);
      await apiStream("/ai/stream", { action: next, symbol, session_id: sessionId, message }, (delta: string) => {
        result += delta;
        setOutput(result);
      });
      return { next, result };
    },
    onSuccess: ({ next, result }: { next: AiAction; result: string }) => {
      if (next === "chat") setQuestion("");
      if (next === "alert") {
        const headline = parseAnswer(result).headline.split("\n")[0] || `${symbol} AI alert`;
        toast(headline, { description: "Read-only AI description of the data. It is not advice." });
        if ("Notification" in window && Notification.permission === "granted") new Notification(`${symbol} · ${headline}`, { body: result.slice(0, 180) });
      }
    },
    onError: (error: unknown) => setProblem(errorMessage(error)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["ai-usage"] }),
  });

  const parsed = useMemo(() => parseAnswer(output), [output]);
  const busy = askMutation.isPending;
  const usage = usageQuery.data;
  const limitText = usage && usage.limit !== null && usage.remaining !== null ? `${usage.remaining} of ${usage.limit} questions left today` : null;
  const closedNote = cards && cards.feed_state !== "LIVE" && cards.feed_state !== "DEMO";
  const label = action === "alert" ? "Notable change" : action === "summary" ? "Session summary" : action === "chat" ? "Answer" : "Explanation of the readings";

  return (
    <Card id="ai" data-testid="claude-analyst-card" className="overflow-hidden border-[#315080]/60 bg-[#101621]/95 shadow-[0_16px_40px_rgba(28,74,135,0.12)]">
      <CardHeader className="border-b border-[#202b42] px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-blue-500/10 text-blue-300"><Bot className="size-[18px]" /></div>
            <div>
              <CardTitle data-testid="claude-analyst-title" className="font-heading text-base text-slate-100">AI Market Analyst</CardTitle>
              <p className="mt-0.5 text-xs text-slate-500">Ask questions about the live options market.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {limitText && <span data-testid="ai-usage-left" className="text-[11px] text-slate-500">{limitText}</span>}
            <Badge data-testid="claude-analyst-status" className={configured ? "border-blue-500/30 bg-blue-500/10 text-[10px] text-blue-300" : "border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300"}>{!configured ? "OFFLINE" : busy ? "WORKING" : "READY"}</Badge>
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-slate-500">Claude AI analyzes the live market data shown in your dashboard. It doesn't supply the market feed, it can be wrong, and it only describes the data. It doesn't tell you what to trade.</p>
      </CardHeader>

      <CardContent className="space-y-6 p-4 sm:p-5">
        <section aria-labelledby="insight-cards-title">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 id="insight-cards-title" className="font-heading text-sm font-semibold text-slate-100">Insight cards · {symbol}</h3>
              <p className="mt-0.5 text-[11px] text-slate-500">
                {cards ? `Data as of ${clock(cards.data_as_of)} IST · written ${clock(cards.generated_at)}` : "Five short readings of the current chain. Generated when you ask, then shared with everyone for a few minutes."}
              </p>
            </div>
            <Button data-testid="insight-generate" type="button" variant="outline" size="sm" className="border-[#2a364f] bg-[#0e131d] text-slate-200" disabled={!configured || cardsMutation.isPending} onClick={() => cardsMutation.mutate()}>
              <RefreshCw className={`mr-2 size-3.5 ${cardsMutation.isPending ? "motion-safe:animate-spin" : ""}`} />
              {cardsMutation.isPending ? "Reading the chain…" : cards ? "Refresh insights" : "Generate insights"}
            </Button>
          </div>
          {cards?.note && <p data-testid="insight-note" className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-200">{cards.note} The figures below are still live data.</p>}
          {closedNote && <p data-testid="insight-closed" className="mt-3 rounded-lg border border-[#26334b] bg-[#131b2a] px-3 py-2 text-xs text-slate-300">Market {cards?.feed_state === "MARKET_CLOSED" ? "closed" : "data delayed"}: these cards use the latest available data, not live prices.</p>}
          {cardsStale && !cardsMutation.isPending && <p data-testid="insight-stale" className="mt-3 text-[11px] text-amber-300/90">These cards may be outdated because the market has moved since {clock(cards?.generated_at)}. Refresh for a new reading.</p>}
          {cards ? (
            <div data-testid="insight-grid" className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {cards.cards.map((card) => <InsightCardView key={card.id} card={card} dataAsOf={cards.data_as_of} stale={cardsStale} />)}
            </div>
          ) : (
            <p className="mt-4 rounded-lg border border-dashed border-[#26334b] px-4 py-6 text-center text-xs text-slate-500">{cachedCards.isError ? "Insight cards are unavailable right now." : "OI, PCR, volatility, Greeks and market structure cards appear here."}</p>
          )}
        </section>

        <section aria-labelledby="ask-title" className="space-y-3 border-t border-[#202b42] pt-5">
          <h3 id="ask-title" className="font-heading text-sm font-semibold text-slate-100">Ask about this chain</h3>
          <div data-testid="suggested-questions" className="flex flex-wrap gap-2">
            {SUGGESTED_QUESTIONS.map((suggestion) => (
              <button key={suggestion} type="button" disabled={!configured || busy} onClick={() => askMutation.mutate({ action: "chat", message: suggestion })} className="rounded-full border border-[#2a364f] bg-[#0e131d] px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-blue-400/40 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/50 disabled:opacity-50">
                {suggestion}
              </button>
            ))}
          </div>
          <div data-testid="claude-action-grid" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Button data-testid="claude-explain-button" type="button" variant="outline" size="sm" className="justify-start border-[#2a364f] bg-[#0e131d] text-slate-300" disabled={!configured || busy} onClick={() => askMutation.mutate({ action: "explain" })}><Sparkles className="mr-2 size-3.5 text-blue-300" />Explain readings</Button>
            <Button data-testid="claude-summary-button" type="button" variant="outline" size="sm" className="justify-start border-[#2a364f] bg-[#0e131d] text-slate-300" disabled={!configured || busy} onClick={() => askMutation.mutate({ action: "summary" })}><FileText className="mr-2 size-3.5 text-blue-300" />Daily summary</Button>
            <Button data-testid="claude-alert-button" type="button" variant="outline" size="sm" className="justify-start border-amber-500/25 bg-amber-500/5 text-amber-200" disabled={!configured || busy} onClick={() => askMutation.mutate({ action: "alert" })}><Bell className="mr-2 size-3.5" />Notable change</Button>
            <Button data-testid="claude-notifications-button" type="button" variant="outline" size="sm" className="justify-start border-[#2a364f] bg-[#0e131d] text-slate-400" onClick={onEnableNotifications}><Bell className="mr-2 size-3.5" />Enable notify</Button>
          </div>

          <div data-testid="claude-output-panel" aria-live="polite" className="min-h-28 rounded-lg border border-[#202b42] bg-[#090d15] p-4">
            <div className="flex items-center justify-between gap-2">
              <p data-testid="claude-output-label" className="text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-300/80">{label}</p>
              {contextAt && <p data-testid="ai-context-time" className="text-[10px] text-slate-500">AI context updated: {clock(contextAt)} IST</p>}
            </div>
            {problem ? (
              <p data-testid="ai-problem" role="alert" className="mt-3 text-xs leading-relaxed text-rose-200">{problem}</p>
            ) : !output ? (
              <p data-testid="claude-output-text" className="mt-3 text-xs leading-relaxed text-slate-500">{busy ? "Reading the option chain and checking every figure…" : "Pick a question above or type your own."}</p>
            ) : parsed.plain ? (
              <p data-testid="claude-output-text" className="mt-3 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{parsed.plain}</p>
            ) : (
              <div data-testid="claude-output-text" className="mt-3 space-y-3">
                {demo && <p className="text-[11px] text-amber-300">Demo mode: this describes simulated data.</p>}
                {parsed.lead && <p className="text-xs text-slate-400">{parsed.lead}</p>}
                {parsed.headline && <p className="font-heading text-sm font-semibold text-slate-100">{parsed.headline}</p>}
                {parsed.data && <div><Chip tone="data" label="Data" /><p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-slate-200">{parsed.data}</p></div>}
                {parsed.interpretation && <div><Chip tone="ai" label="AI interpretation" /><p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{parsed.interpretation}</p></div>}
              </div>
            )}
          </div>

          <form data-testid="claude-chat-form" className="space-y-2" onSubmit={(event) => { event.preventDefault(); const text = question.trim(); if (text && configured && !busy) askMutation.mutate({ action: "chat", message: text }); }}>
            <label htmlFor="claude-chat-input" className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500"><MessageSquare className="size-3" />Your question</label>
            <div className="flex gap-2">
              <Textarea id="claude-chat-input" data-testid="claude-chat-input" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} rows={2} placeholder="Where is put open interest building?" className="min-h-16 resize-none border-[#2a364f] bg-[#0e131d] text-xs text-slate-200 placeholder:text-slate-600" />
              <Button data-testid="claude-chat-submit" type="submit" size="icon" aria-label="Ask" className="h-auto min-h-16 shrink-0 bg-blue-600 text-white hover:bg-blue-500" disabled={!configured || busy || !question.trim()}><Send className="size-4" /></Button>
            </div>
          </form>
          <p data-testid="claude-disclaimer" className="text-[10px] leading-relaxed text-slate-600">AI describes the data on this dashboard, and every figure is checked against it before you see it. It can still be wrong and is not investment advice. It never places orders. IV, delta, gamma, theta and vega are model estimates.</p>
        </section>
      </CardContent>
    </Card>
  );
}
