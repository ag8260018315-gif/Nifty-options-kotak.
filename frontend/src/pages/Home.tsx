import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpRight, Bell, Bot, Check, ChevronDown, CircleHelp, Cloud, Download, FileText, Gauge, KeyRound, LockKeyhole, MessageSquare, RefreshCw, Save, Send, Settings2, ShieldCheck, Sparkles, Sunrise, Wifi } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Toaster } from "@/components/ui/sonner";
import { Textarea } from "@/components/ui/textarea";
import { apiDownload, apiGet, apiPost, apiPut, apiStream } from "@/lib/api";

type IndexSymbol = "NIFTY" | "BANKNIFTY" | "FINNIFTY";
type MarketState = "LIVE" | "STALE" | "EXPIRED" | "MARKET_CLOSED" | "DISCONNECTED" | "DEMO";

interface SpotSnapshot {
  symbol: IndexSymbol;
  ltp: number;
  change: number;
  pct_change: number;
  high: number;
  low: number;
  timestamp: string | null;
}

interface OptionLeg {
  ltp: number;
  change: number;
  oi: number;
  oi_change: number;
  iv: number;
  delta: number;
}

interface OptionRow {
  strike: number;
  call: OptionLeg;
  put: OptionLeg;
  is_atm: boolean;
}

interface MarketStructure {
  pcr: number;
  max_pain: number;
  bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  oi_buildup: string;
}

interface SignalSnapshot {
  recommendation: "BUY CALLS" | "BUY PUTS" | "WAIT";
  confidence: number;
  reasons: string[];
  timestamp: string | null;
}

interface FeedHealth {
  state: MarketState;
  source: "KOTAK_NEO" | "DEMO";
  last_tick: string | null;
  heartbeat_ms: number;
  subscriptions: number;
  divider_status: "VERIFIED" | "PENDING";
}

interface DashboardSnapshot {
  symbol: IndexSymbol;
  expiry: string;
  spot: SpotSnapshot;
  option_chain: OptionRow[];
  structure: MarketStructure;
  signal: SignalSnapshot;
  feed: FeedHealth;
  as_of: string;
}

interface AuthStatus {
  mode: "DEMO" | "LIVE";
  state: "DEMO" | "DISCONNECTED" | "LIVE" | "EXPIRED";
  configured: boolean;
  connected: boolean;
  configured_fields: string[];
  missing_fields: string[];
  feed_connected: boolean;
  message: string;
}

type FeedAlertType = "ATM_SHIFT" | "EXPIRY_DAY" | "NEAR_CLOSE" | "ROLL_REQUIRED" | "OPENING_REPORT" | "EXPORT_READY";

interface FeedAlert {
  id: string;
  type: FeedAlertType;
  title: string;
  message: string;
  created_at: string;
  symbol: IndexSymbol | null;
}

interface AlertSettings {
  atm_shift_steps: number;
  cooldown_seconds: number;
  quiet_start: string;
  quiet_end: string;
}

interface IndexFeedStatus {
  symbol: IndexSymbol;
  state: Exclude<MarketState, "DISCONNECTED">;
  last_tick: string | null;
  atm_strike: number | null;
  expiry: string | null;
  option_subscriptions: number;
  paired_strikes: number;
  expected_pairs: number;
}

interface OpeningIndexHealth {
  symbol: IndexSymbol;
  fresh_spot: boolean;
  divider_verified: boolean;
  option_window_complete: boolean;
  paired_ce_pe_complete: boolean;
  socket_connected: boolean;
  option_subscriptions: number;
  paired_strikes: number;
}

interface OpeningReport {
  session_date: string;
  generated_at: string;
  status: "PASS" | "WARN";
  indices: OpeningIndexHealth[];
}

interface FeedStatus {
  state: Exclude<MarketState, "DISCONNECTED">;
  connected: boolean;
  authenticated: boolean;
  last_tick: string | null;
  subscriptions: number;
  divider_verified: boolean;
  atm_strike: number | null;
  expiry: string | null;
  message: string;
  alerts: FeedAlert[];
  indices: IndexFeedStatus[];
  opening_report: OpeningReport | null;
  alert_settings: AlertSettings;
}

interface ExportArchiveItem {
  symbol: IndexSymbol;
  available: boolean;
  snapshot_count: number;
  row_count: number;
  first_capture: string | null;
  last_capture: string | null;
  filename: string | null;
}

interface ExportArchiveResponse {
  trading_day: string;
  prepared_at: string | null;
  items: ExportArchiveItem[];
}

type AiAction = "explain" | "chat" | "summary" | "alert";

interface AiStatus {
  configured: boolean;
  provider: "anthropic";
  model: string;
  capabilities: AiAction[];
}

interface AiAnalysisRequest {
  action: AiAction;
  symbol: IndexSymbol;
  session_id: string;
  message?: string;
}

const SYMBOLS: IndexSymbol[] = ["NIFTY", "BANKNIFTY", "FINNIFTY"];
const numberFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const integerFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

const fetchDashboard = (symbol: IndexSymbol) =>
  apiGet<DashboardSnapshot>(`/market-data/dashboard?symbol=${symbol}`);
const fetchAuthStatus = () => apiGet<AuthStatus>("/auth/status");
const fetchAiStatus = () => apiGet<AiStatus>("/ai/status");
const fetchFeedStatus = () => apiGet<FeedStatus>("/market-data/feed-status");
const fetchExportArchive = () => apiGet<ExportArchiveResponse>("/market-data/export-archive");

function formatPrice(value: number) {
  return numberFormat.format(value);
}

function formatInteger(value: number) {
  return integerFormat.format(value);
}

function stateLabel(state: MarketState) {
  return state === "MARKET_CLOSED" ? "MARKET CLOSED" : state;
}

function stateStyles(state: MarketState) {
  if (state === "LIVE") return "border-emerald-500/35 bg-emerald-950/70 text-emerald-300";
  if (state === "STALE") return "border-amber-500/35 bg-amber-950/70 text-amber-300";
  if (state === "EXPIRED") return "border-rose-500/35 bg-rose-950/70 text-rose-300";
  if (state === "MARKET_CLOSED") return "border-zinc-700/60 bg-zinc-900/90 text-zinc-300";
  if (state === "DISCONNECTED") return "border-rose-500/35 bg-rose-950/70 text-rose-300";
  return "border-indigo-500/35 bg-indigo-950/70 text-indigo-300";
}

function modeStyles(mode: "DEMO" | "LIVE") {
  return mode === "LIVE"
    ? "border-emerald-500/30 bg-emerald-950/70 text-emerald-300"
    : "border-indigo-500/30 bg-indigo-950/70 text-indigo-300";
}

function MetricCard({ label, value, detail, icon: Icon, accent = "text-slate-100", testId }: { label: string; value: string; detail: string; icon: typeof Activity; accent?: string; testId: string }) {
  return (
    <Card size="sm" className="data-hover border-[#202b42] bg-[#101621]/90 shadow-[0_12px_30px_rgba(0,0,0,0.16)]">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <p data-testid={`${testId}-label`} className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
          <Icon data-testid={`${testId}-icon`} className="size-4 text-slate-600" />
        </div>
        <p data-testid={testId} className={`mt-2 font-mono text-xl font-bold tabular-nums tracking-tight ${accent}`}>{value}</p>
        <p data-testid={`${testId}-detail`} className="mt-1 text-xs text-slate-500">{detail}</p>
      </CardContent>
    </Card>
  );
}

export default function Home() {
  const queryClient = useQueryClient();
  const [symbol, setSymbol] = useState<IndexSymbol>("NIFTY");
  const [range, setRange] = useState("5");
  const [connectOpen, setConnectOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const [aiOutput, setAiOutput] = useState("");
  const [aiAction, setAiAction] = useState<AiAction>("explain");
  const [chatQuestion, setChatQuestion] = useState("");
  const [aiSessionId] = useState(() => window.crypto.randomUUID());
  const [atmShiftSteps, setAtmShiftSteps] = useState(1);
  const [cooldownSeconds, setCooldownSeconds] = useState(60);
  const [quietStart, setQuietStart] = useState("15:30");
  const [quietEnd, setQuietEnd] = useState("09:15");
  const seenFeedAlerts = useRef<Set<string>>(new Set());
  const alertsInitialized = useRef(false);
  const alertSettingsInitialized = useRef(false);

  const dashboardQuery = useQuery({
    queryKey: ["dashboard", symbol],
    queryFn: () => fetchDashboard(symbol),
    refetchInterval: 5000,
    retry: false,
  });
  const authQuery = useQuery({ queryKey: ["auth-status"], queryFn: fetchAuthStatus, retry: false });
  const aiStatusQuery = useQuery({ queryKey: ["ai-status"], queryFn: fetchAiStatus, retry: false });
  const feedStatusQuery = useQuery({ queryKey: ["feed-status"], queryFn: fetchFeedStatus, refetchInterval: 2000, retry: false });
  const exportArchiveQuery = useQuery({ queryKey: ["export-archive"], queryFn: fetchExportArchive, refetchInterval: 30000, retry: false });

  useEffect(() => {
    const alerts = feedStatusQuery.data?.alerts ?? [];
    if (!alertsInitialized.current) {
      alerts.forEach((alert) => seenFeedAlerts.current.add(alert.id));
      alertsInitialized.current = true;
      return;
    }
    for (const alert of alerts) {
      if (seenFeedAlerts.current.has(alert.id)) continue;
      seenFeedAlerts.current.add(alert.id);
      toast(alert.title, { description: alert.message });
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(alert.title, { body: alert.message });
      }
    }
  }, [feedStatusQuery.data?.alerts]);

  useEffect(() => {
    const current = feedStatusQuery.data?.alert_settings;
    if (!current || alertSettingsInitialized.current) return;
    setAtmShiftSteps(current.atm_shift_steps);
    setCooldownSeconds(current.cooldown_seconds);
    setQuietStart(current.quiet_start);
    setQuietEnd(current.quiet_end);
    alertSettingsInitialized.current = true;
  }, [feedStatusQuery.data?.alert_settings]);

  const demoMutation = useMutation({
    mutationFn: () => apiPost<AuthStatus>("/auth/demo", { confirm: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth-status"] });
      setDemoOpen(false);
      toast.success("DEMO mode confirmed", { description: "Simulated data remains visibly labeled." });
    },
    onError: () => toast.error("Demo mode could not be confirmed"),
  });

  const connectMutation = useMutation({
    mutationFn: () => apiPost<AuthStatus>("/auth/connect", {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth-status"] });
      setConnectOpen(false);
      toast.success("Kotak connection updated");
    },
    onError: () => toast.info("Credentials are not configured yet", { description: "Add them only to backend/.env, then retry this check." }),
  });

  const alertSettingsMutation = useMutation({
    mutationFn: (request: AlertSettings) => apiPut<AlertSettings>("/market-data/alert-settings", request),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["feed-status"] });
      toast.success("Alert controls saved");
    },
    onError: () => toast.error("Alert controls could not be saved"),
  });

  const exportMutation = useMutation({
    mutationFn: async (target: IndexSymbol) => ({ target, ...(await apiDownload(`/market-data/export.csv?symbol=${target}`)) }),
    onSuccess: ({ blob, filename, target }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast.success(`${target} CSV exported`, { description: "Verified Kotak snapshots from the current trading day." });
    },
    onError: () => toast.error("No verified live data is available to export yet"),
  });

  const aiMutation = useMutation({
    mutationFn: async ({ action, message }: { action: AiAction; message?: string }) => {
      let result = "";
      setAiAction(action);
      setAiOutput("");
      const request: AiAnalysisRequest = { action, symbol, session_id: aiSessionId, message };
      await apiStream("/ai/stream", request, (delta) => {
        result += delta;
        setAiOutput(result);
      });
      return { action, result };
    },
    onSuccess: ({ action, result }) => {
      if (action === "chat") setChatQuestion("");
      if (action === "alert") {
        const headline = result.split("\n")[0] || `${symbol} AI alert`;
        toast(headline, { description: "Read-only Claude analysis. Review the invalidation before acting." });
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification(`${symbol} · ${headline}`, { body: result.slice(0, 180) });
        }
      }
    },
    onError: () => toast.error("Claude analysis is temporarily unavailable"),
  });

  const enableNotifications = async () => {
    if (!("Notification" in window)) {
      toast.info("Browser notifications are not supported here");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission === "granted") toast.success("CE/PE browser alerts enabled");
    else toast.info("Notifications remain off");
  };

  const data = dashboardQuery.data;
  const modeLabel = authQuery.data?.mode ?? "DEMO";
  const selectedIndexFeed = feedStatusQuery.data?.indices.find((item) => item.symbol === symbol);
  const feedState = (selectedIndexFeed?.state ?? feedStatusQuery.data?.state ?? data?.feed.state ?? (authQuery.data?.state === "LIVE" ? "STALE" : authQuery.data?.state ?? "DEMO")) as MarketState;
  const visibleRows = useMemo(() => {
    if (!data) return [];
    const width = Number(range);
    const atmIndex = data.option_chain.findIndex((row) => row.is_atm);
    if (atmIndex < 0) return data.option_chain.slice(0, width * 2 + 1);
    return data.option_chain.slice(Math.max(0, atmIndex - width), atmIndex + width + 1);
  }, [data, range]);
  const authMessage = authQuery.data?.message ?? "Checking the server-side Kotak configuration…";
  const lastTickValue = selectedIndexFeed?.last_tick ?? (feedStatusQuery.data ? null : data?.feed.last_tick);
  const lastTick = lastTickValue ? new Date(lastTickValue).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
  const latestFeedAlert = feedStatusQuery.data?.alerts.find((alert) => alert.symbol === null || alert.symbol === symbol);
  const hasMarketTick = data?.feed.source === "DEMO" || Boolean(selectedIndexFeed?.last_tick);
  const hasChainData = visibleRows.length > 0;
  const canExport = Boolean(data?.feed.source === "KOTAK_NEO" && data.feed.last_tick && data.option_chain.length >= 21);

  return (
    <div data-testid="app-shell" className="min-h-svh bg-[#07090e] text-slate-100">
      <Toaster richColors />
      <header data-testid="app-header" className="sticky top-0 z-30 border-b border-[#1e2638] bg-[#080b12]/90 px-4 py-3 backdrop-blur-xl sm:px-6">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center justify-between gap-6">
            <div className="flex items-center gap-3">
              <div data-testid="brand-mark" className="flex size-9 items-center justify-center rounded-lg bg-[#e31837] shadow-[0_0_22px_rgba(227,24,55,0.28)]"><Activity className="size-5 text-white" /></div>
              <div>
                <p data-testid="brand-name" className="font-heading text-sm font-semibold tracking-wide text-white">NIFTY OPTIONS DESK</p>
                <p data-testid="brand-subtitle" className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Kotak Neo · Read-only terminal</p>
              </div>
            </div>
            <div className="flex items-center gap-2 xl:hidden">
              <Badge data-testid="mobile-mode-pill" className={`${modeStyles(modeLabel)} text-[10px]`}>{modeLabel}</Badge>
              <Button data-testid="mobile-connect-kotak-button" variant="outline" size="sm" className="border-[#2a364f] bg-transparent text-slate-200" onClick={() => setConnectOpen(true)}>Connect</Button>
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <nav data-testid="index-selector" className="flex items-center gap-1 rounded-lg border border-[#202b42] bg-[#0e131d] p-1">
              {SYMBOLS.map((item) => (
                <button key={item} data-testid={`index-selector-${item.toLowerCase()}`} type="button" onClick={() => setSymbol(item)} className={`data-hover rounded-md px-3 py-2 text-[11px] font-semibold tracking-wide ${symbol === item ? "bg-[#1f2a41] text-white shadow-inner" : "text-slate-500 hover:text-slate-200"}`}>
                  {item}
                </button>
              ))}
            </nav>
            <div data-testid="market-status-banner" className={`flex min-h-10 items-center justify-between gap-4 rounded-lg border px-3 py-2 ${stateStyles(feedState)}`}>
              <div className="flex items-center gap-2">
                <span data-testid="banner-status-indicator" className={`size-2 rounded-full ${feedState === "LIVE" ? "bg-emerald-400 animate-pulse" : feedState === "STALE" ? "bg-amber-400 animate-ping" : feedState === "EXPIRED" ? "bg-rose-500" : "bg-indigo-400"}`} />
                <span data-testid="banner-status-label" className="text-[11px] font-bold tracking-[0.14em]">{stateLabel(feedState)}</span>
              </div>
              <span data-testid="banner-last-tick-time" className="font-mono text-[10px] tabular-nums opacity-80">tick {lastTick}</span>
              {feedState === "EXPIRED" && <button data-testid="banner-relogin-action" type="button" className="text-[10px] font-bold underline" onClick={() => setConnectOpen(true)}>RE-LOGIN</button>}
            </div>
            <div className="hidden items-center gap-2 xl:flex">
              <Badge data-testid="mode-pill" className={`${modeStyles(modeLabel)} text-[10px]`}><span className={`mr-1.5 size-1.5 rounded-full ${modeLabel === "LIVE" ? "bg-emerald-400" : "bg-indigo-400"}`} />{modeLabel}</Badge>
              <Button data-testid="connect-kotak-button" size="sm" className="bg-[#e31837] text-white shadow-[0_0_20px_rgba(227,24,55,0.16)] hover:bg-[#c8102e]" onClick={() => setConnectOpen(true)}><KeyRound className="mr-2 size-3.5" />Connect Kotak Neo</Button>
            </div>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-[1600px] space-y-4 px-4 py-5 sm:px-6">
        <div className="pointer-events-none absolute left-0 right-0 top-0 h-32 overflow-hidden opacity-20"><div className="scanline h-0.5 w-full bg-gradient-to-r from-transparent via-blue-400 to-transparent" /></div>
        <section data-testid="dashboard-intro" className="relative flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p data-testid="terminal-overline" className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#e31837]">Market structure / {symbol}</p>
            <h1 data-testid="dashboard-title" className="mt-1 font-heading text-2xl font-bold tracking-tight text-white sm:text-3xl">Options intelligence, without the noise.</h1>
            <p data-testid="dashboard-description" className="mt-1 max-w-2xl text-sm text-slate-500">Normalized chain data for indicators and signal context. No order placement. No silent source switching.</p>
          </div>
          <div data-testid="data-integrity-note" className="flex items-center gap-2 self-start rounded-md border border-[#202b42] bg-[#0e131d]/70 px-3 py-2 text-[10px] text-slate-500 sm:self-auto"><ShieldCheck className="size-3.5 text-emerald-400" />Data integrity guard active</div>
        </section>

        {latestFeedAlert && <section data-testid="feed-alert-banner" className="flex flex-col gap-2 rounded-lg border border-amber-500/25 bg-amber-500/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-2.5"><Bell data-testid="feed-alert-icon" className="mt-0.5 size-4 shrink-0 text-amber-300" /><div><p data-testid="feed-alert-title" className="text-xs font-semibold text-amber-200">{latestFeedAlert.title}</p><p data-testid="feed-alert-message" className="mt-0.5 text-[11px] text-amber-100/60">{latestFeedAlert.message}</p></div></div><Badge data-testid="feed-alert-type" className="self-start border-amber-500/25 bg-amber-500/10 text-[9px] text-amber-300 sm:self-auto">{latestFeedAlert.type.replaceAll("_", " ")}</Badge></section>}

        <section data-testid="opening-bell-report" className="rounded-xl border border-[#202b42] bg-[#0e131d]/90 px-4 py-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3"><div data-testid="opening-bell-icon" className="flex size-9 items-center justify-center rounded-lg bg-amber-500/10 text-amber-300"><Sunrise className="size-4" /></div><div><p data-testid="opening-bell-title" className="text-sm font-semibold text-slate-200">09:16 opening bell check</p><p data-testid="opening-bell-subtitle" className="mt-0.5 text-[11px] text-slate-500">Fresh spot · divider · ATM ±10 · paired CE/PE · socket</p></div></div>
            {feedStatusQuery.data?.opening_report ? <div className="flex flex-wrap items-center gap-2"><Badge data-testid="opening-report-status" className={feedStatusQuery.data.opening_report.status === "PASS" ? "border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300" : "border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300"}>{feedStatusQuery.data.opening_report.status}</Badge>{feedStatusQuery.data.opening_report.indices.map((item) => <span key={item.symbol} data-testid={`opening-report-${item.symbol.toLowerCase()}`} className="rounded-md border border-[#2a364f] bg-[#090d15] px-2.5 py-1.5 font-mono text-[10px] text-slate-400">{item.symbol} {item.fresh_spot && item.divider_verified && item.option_window_complete && item.paired_ce_pe_complete && item.socket_connected ? "✓" : "CHECK"} · {item.paired_strikes}/{21} pairs</span>)}</div> : <Badge data-testid="opening-report-status" className="border-slate-600/40 bg-slate-800/50 text-[10px] text-slate-400">SCHEDULED · 09:16 IST</Badge>}
          </div>
        </section>

        <section data-testid="export-archive-card" className="rounded-xl border border-emerald-500/15 bg-[#0e131d]/90 px-4 py-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3"><div data-testid="export-archive-icon" className="flex size-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-300"><Download className="size-4" /></div><div><p data-testid="export-archive-title" className="text-sm font-semibold text-slate-200">Today’s verified exports</p><p data-testid="export-archive-status" className="mt-0.5 text-[11px] text-slate-500">{exportArchiveQuery.data?.prepared_at ? `Closing manifest prepared ${new Date(exportArchiveQuery.data.prepared_at).toLocaleTimeString("en-IN")}` : "Closing manifest prepares automatically after 15:31 IST"}</p></div></div>
            <div className="flex flex-wrap gap-2">{(exportArchiveQuery.data?.items ?? []).map((item) => <div key={item.symbol} data-testid={`export-archive-item-${item.symbol.toLowerCase()}`} className="flex items-center gap-2 rounded-lg border border-[#253149] bg-[#090d15] px-2.5 py-2"><div><p data-testid={`export-archive-symbol-${item.symbol.toLowerCase()}`} className="font-mono text-[10px] font-semibold text-slate-300">{item.symbol}</p><p data-testid={`export-archive-count-${item.symbol.toLowerCase()}`} className="text-[9px] text-slate-600">{item.available ? `${item.snapshot_count} snapshots · ${item.row_count} rows` : "Waiting for verified ticks"}</p></div><Button data-testid={`export-archive-download-${item.symbol.toLowerCase()}`} type="button" variant="ghost" size="icon" className="size-7 text-emerald-300 hover:bg-emerald-500/10" disabled={!item.available || exportMutation.isPending} onClick={() => exportMutation.mutate(item.symbol)}><Download className="size-3.5" /></Button></div>)}</div>
          </div>
        </section>

        <section data-testid="market-summary-grid" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card size="sm" className="border-[#202b42] bg-[#101621]/90 sm:col-span-2 xl:col-span-1">
            <CardContent className="p-4">
              <div className="flex items-start justify-between"><p data-testid="ticker-spot-price-label" className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Spot price</p><span data-testid="ticker-atm-strike-badge" className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 font-mono text-[10px] text-blue-300">ATM {hasMarketTick ? data?.structure.max_pain ?? "—" : "—"}</span></div>
              <p data-testid="ticker-spot-price" className="mt-2 font-mono text-2xl font-bold tabular-nums tracking-tight text-white">{data && hasMarketTick ? formatPrice(data.spot.ltp) : "—"}</p>
              <div className="mt-1 flex items-center gap-2"><span data-testid="ticker-day-change" className="font-mono text-xs font-semibold text-emerald-400">{data && hasMarketTick ? `${data.spot.change >= 0 ? "+" : ""}${formatPrice(data.spot.change)} (${data.spot.pct_change >= 0 ? "+" : ""}${data.spot.pct_change}%)` : "Waiting for first Kotak tick"}</span>{hasMarketTick && <ArrowUpRight className="size-3 text-emerald-400" />}</div>
              <div className="mt-3 flex justify-between border-t border-[#202b42] pt-2 text-[10px] text-slate-500"><span data-testid="ticker-day-range-high">H {data && hasMarketTick ? formatPrice(data.spot.high) : "—"}</span><span data-testid="ticker-day-range-low">L {data && hasMarketTick ? formatPrice(data.spot.low) : "—"}</span></div>
            </CardContent>
          </Card>
          <MetricCard label="Put / call ratio" value={data && hasChainData ? data.structure.pcr.toFixed(2) : "—"} detail={data?.structure.oi_buildup ?? "Awaiting option chain"} icon={Gauge} accent="text-blue-300" testId="pcr-gauge-value" />
          <MetricCard label="Max pain" value={data && hasChainData ? formatInteger(data.structure.max_pain) : "—"} detail={data && hasChainData ? `${data.structure.bias} structure bias` : "Awaiting live option ticks"} icon={Activity} accent={data?.structure.bias === "BULLISH" ? "text-emerald-300" : "text-slate-100"} testId="max-pain-value" />
          <MetricCard label="SFeed socket health" value={feedStatusQuery.data?.connected ? "CONNECTED" : feedState} detail={selectedIndexFeed ? `${selectedIndexFeed.option_subscriptions + 1} ${symbol} instruments · ${selectedIndexFeed.paired_strikes}/${selectedIndexFeed.expected_pairs} paired` : "Server feed health pending"} icon={Wifi} accent={feedStatusQuery.data?.connected ? "text-emerald-300" : "text-amber-300"} testId="feed-health-value" />
        </section>

        <section className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(320px,5fr)]">
          <Card data-testid="option-chain-container" className="overflow-hidden border-[#202b42] bg-[#0c0f17]/95 shadow-[0_20px_50px_rgba(0,0,0,0.18)]">
            <CardHeader className="border-b border-[#202b42] px-4 py-3 sm:px-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div><CardTitle data-testid="option-chain-title" className="font-heading text-base text-slate-100">Option chain / Greeks ladder</CardTitle><p data-testid="option-chain-subtitle" className="mt-1 text-xs text-slate-500">Calls on the left · puts on the right · ATM highlighted</p></div>
                <div className="flex items-center gap-2">
                  <Button data-testid="export-csv-button" type="button" variant="outline" size="sm" className="border-emerald-500/25 bg-emerald-500/5 text-[11px] text-emerald-300 hover:bg-emerald-500/10" disabled={!canExport || exportMutation.isPending} title={canExport ? `Export today's verified ${symbol} snapshots` : "Available after the first verified Kotak option snapshot"} onClick={() => exportMutation.mutate(symbol)}><Download className="mr-1.5 size-3.5" />{exportMutation.isPending ? "Preparing…" : "Export CSV"}</Button>
                  <label data-testid="strike-filter-label" htmlFor="strike-filter-range" className="sr-only">Strike range</label>
                  <select id="strike-filter-range" data-testid="strike-filter-range" value={range} onChange={(event) => setRange(event.target.value)} className="rounded-md border border-[#2a364f] bg-[#111622] px-2.5 py-2 text-[11px] text-slate-300 outline-none focus:border-blue-500"><option value="3">±3 strikes</option><option value="5">±5 strikes</option><option value="10">±10 strikes</option></select>
                  <label data-testid="expiry-date-label" htmlFor="expiry-date-select" className="sr-only">Expiry</label>
                  <select id="expiry-date-select" data-testid="expiry-date-select" defaultValue="current" className="rounded-md border border-[#2a364f] bg-[#111622] px-2.5 py-2 text-[11px] text-slate-300 outline-none focus:border-blue-500"><option value="current">{data?.expiry ?? "Current expiry"}</option></select>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <p data-testid="export-status-message" className="border-b border-[#202b42] px-4 py-2 text-[10px] text-slate-600">{canExport ? `CSV includes all verified ${symbol} snapshots captured today` : "CSV unlocks after the first verified Kotak spot and paired CE/PE snapshot"}</p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[880px] border-collapse text-right">
                  <thead data-testid="option-chain-table-head" className="bg-[#0e131d] text-[9px] uppercase tracking-[0.12em] text-slate-500"><tr><th colSpan={5} className="border-r border-[#202b42] px-2 py-2 text-center text-emerald-400/80">Call side</th><th rowSpan={2} className="bg-[#141c2b] px-3 py-2 text-center text-blue-300">Strike</th><th colSpan={5} className="px-2 py-2 text-center text-rose-300/80">Put side</th></tr><tr><th className="px-2 pb-2">OI chg</th><th className="px-2 pb-2">OI</th><th className="px-2 pb-2">IV</th><th className="px-2 pb-2">Delta</th><th className="border-r border-[#202b42] px-2 pb-2">LTP</th><th className="px-2 pb-2">LTP</th><th className="px-2 pb-2">Delta</th><th className="px-2 pb-2">IV</th><th className="px-2 pb-2">OI</th><th className="px-2 pb-2">OI chg</th></tr></thead>
                  <tbody data-testid="option-chain-table-body">{visibleRows.map((row) => <tr key={row.strike} data-testid={`option-chain-row-${row.strike}`} className={`data-hover border-t border-[#182134] text-xs font-mono tabular-nums ${row.is_atm ? "bg-[#1e293b]/80" : "odd:bg-[#0e131d]/70"}`}>
                    <td className={`px-2 py-3 ${row.call.oi_change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{row.call.oi_change >= 0 ? "+" : ""}{formatInteger(row.call.oi_change)}</td><td className="relative px-2 py-3 text-slate-300"><div data-testid={`call-oi-bar-${row.strike}`} className="absolute bottom-1 right-1 h-0.5 bg-emerald-500/40" style={{ width: `${Math.min(70, row.call.oi / 2000)}%` }} />{formatInteger(row.call.oi)}</td><td className="px-2 py-3 text-slate-400">{row.call.iv.toFixed(1)}%</td><td className="px-2 py-3 text-emerald-300">{row.call.delta.toFixed(2)}</td><td data-testid={`call-ltp-cell-${row.strike}`} className="border-r border-[#202b42] px-2 py-3 font-semibold text-emerald-300">{formatPrice(row.call.ltp)}</td>
                    <td data-testid={`strike-cell-${row.strike}`} className={`bg-[#141c2b] px-3 py-3 text-center font-semibold ${row.is_atm ? "text-blue-200" : "text-slate-100"}`}>{row.strike}{row.is_atm && <span data-testid={`atm-marker-${row.strike}`} className="ml-1 text-[8px] text-blue-400">ATM</span>}</td>
                    <td data-testid={`put-ltp-cell-${row.strike}`} className="px-2 py-3 font-semibold text-rose-300">{formatPrice(row.put.ltp)}</td><td className="px-2 py-3 text-rose-300">{row.put.delta.toFixed(2)}</td><td className="px-2 py-3 text-slate-400">{row.put.iv.toFixed(1)}%</td><td className="relative px-2 py-3 text-slate-300"><div data-testid={`put-oi-bar-${row.strike}`} className="absolute bottom-1 left-1 h-0.5 bg-rose-500/40" style={{ width: `${Math.min(70, row.put.oi / 2000)}%` }} />{formatInteger(row.put.oi)}</td><td className={`px-2 py-3 ${row.put.oi_change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{row.put.oi_change >= 0 ? "+" : ""}{formatInteger(row.put.oi_change)}</td>
                  </tr>)}</tbody>
                </table>
              </div>
              <div data-testid="option-chain-footnote" className="flex items-center justify-between border-t border-[#202b42] px-4 py-3 text-[10px] text-slate-500"><span>{data && hasChainData ? `${visibleRows.length} strikes around ATM · ${data.feed.source === "DEMO" ? "simulated" : "Kotak Neo live"} snapshot` : feedStatusQuery.data?.message ?? "Loading normalized chain…"}</span><span className="font-mono tabular-nums">as of {data && hasChainData ? new Date(data.as_of).toLocaleTimeString("en-IN") : "—"}</span></div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card data-testid="market-structure-card" className="border-[#202b42] bg-[#101621]/90"><CardHeader className="flex-row items-center justify-between border-b border-[#202b42] px-4 py-3"><div><CardTitle data-testid="market-structure-title" className="font-heading text-base text-slate-100">Market structure</CardTitle><p data-testid="market-structure-subtitle" className="mt-1 text-xs text-slate-500">What the chain is leaning toward</p></div><CircleHelp data-testid="market-structure-help" className="size-4 text-slate-600" /></CardHeader><CardContent className="space-y-4 p-4"><div className="flex items-center justify-between"><span data-testid="pcr-interpretation-label" className="text-xs text-slate-400">PCR interpretation</span><Badge data-testid="pcr-interpretation-badge" className="border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300">{data && hasChainData ? data.structure.bias : "WAITING"}</Badge></div><div className="grid grid-cols-2 gap-3"><div className="rounded-lg border border-[#202b42] bg-[#0e131d] p-3"><p data-testid="structure-pcr-label" className="text-[10px] uppercase tracking-wider text-slate-500">PCR</p><p data-testid="structure-pcr-value" className="mt-2 font-mono text-lg font-bold text-white">{data && hasChainData ? data.structure.pcr.toFixed(2) : "—"}</p></div><div className="rounded-lg border border-[#202b42] bg-[#0e131d] p-3"><p data-testid="structure-max-pain-label" className="text-[10px] uppercase tracking-wider text-slate-500">Max pain</p><p data-testid="structure-max-pain-value" className="mt-2 font-mono text-lg font-bold text-white">{data && hasChainData ? formatInteger(data.structure.max_pain) : "—"}</p></div></div><div data-testid="oi-buildup-summary" className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-3"><p data-testid="oi-buildup-label" className="text-[10px] uppercase tracking-wider text-blue-300/70">OI buildup</p><p data-testid="oi-buildup-value" className="mt-1 text-sm text-blue-100">{data?.structure.oi_buildup ?? "Waiting for option chain"}</p></div></CardContent></Card>

            <Card data-testid="signal-engine-card" className="signal-pulse border-emerald-500/20 bg-[#101621]/90"><CardHeader className="flex-row items-center justify-between border-b border-[#202b42] px-4 py-3"><div><CardTitle data-testid="signal-engine-title" className="font-heading text-base text-slate-100">Signal engine</CardTitle><p data-testid="signal-engine-subtitle" className="mt-1 text-xs text-slate-500">Normalized inputs · read-only guidance</p></div><Badge data-testid="signal-engine-status" className="border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300">{hasChainData ? "ACTIVE" : "WAITING"}</Badge></CardHeader><CardContent className="space-y-4 p-4"><div className="flex items-end justify-between"><div><p data-testid="signal-recommendation-label" className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Recommendation</p><p data-testid="signal-recommendation-badge" className="mt-1 font-heading text-xl font-bold text-emerald-300">{data?.signal.recommendation ?? "—"}</p></div><div className="text-right"><p data-testid="signal-confidence-label" className="text-[10px] uppercase tracking-wider text-slate-500">Confidence</p><p data-testid="signal-confidence-value" className="mt-1 font-mono text-lg font-bold text-white">{data ? `${data.signal.confidence}%` : "—"}</p></div></div><div data-testid="signal-confidence-meter" className="h-1.5 overflow-hidden rounded-full bg-[#202b42]"><div className="h-full rounded-full bg-emerald-400 transition-[width] duration-500" style={{ width: `${data?.signal.confidence ?? 0}%` }} /></div><ul data-testid="signal-breakdown-reasons" className="space-y-2">{(data?.signal.reasons ?? ["Waiting for normalized market inputs"]).map((reason, index) => <li key={reason} data-testid={`signal-reason-${index}`} className="flex items-start gap-2 text-xs text-slate-400"><Check className="mt-0.5 size-3.5 shrink-0 text-emerald-400" />{reason}</li>)}</ul><p data-testid="signal-timestamp" className="border-t border-[#202b42] pt-3 font-mono text-[10px] text-slate-600">Updated {data && hasChainData && data.signal.timestamp ? new Date(data.signal.timestamp).toLocaleTimeString("en-IN") : "—"} · informational only</p></CardContent></Card>

            <Card data-testid="alert-controls-card" className="border-[#202b42] bg-[#101621]/90">
              <CardHeader className="flex-row items-center justify-between border-b border-[#202b42] px-4 py-3"><div><CardTitle data-testid="alert-controls-title" className="font-heading text-base text-slate-100">Alert controls</CardTitle><p data-testid="alert-controls-subtitle" className="mt-1 text-xs text-slate-500">ATM sensitivity, cooldown, and quiet hours</p></div><Settings2 data-testid="alert-controls-icon" className="size-4 text-slate-600" /></CardHeader>
              <CardContent className="p-4"><form data-testid="alert-controls-form" className="space-y-3" onSubmit={(event) => { event.preventDefault(); alertSettingsMutation.mutate({ atm_shift_steps: atmShiftSteps, cooldown_seconds: cooldownSeconds, quiet_start: quietStart, quiet_end: quietEnd }); }}>
                <div className="grid grid-cols-2 gap-3"><div><label data-testid="atm-threshold-label" htmlFor="atm-threshold-select" className="text-[10px] uppercase tracking-wider text-slate-500">ATM shift</label><select id="atm-threshold-select" data-testid="atm-threshold-select" value={atmShiftSteps} onChange={(event) => setAtmShiftSteps(Number(event.target.value))} className="mt-1.5 w-full rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 py-2 text-xs text-slate-300"><option value={1}>1 full strike</option><option value={2}>2 full strikes</option><option value={3}>3 full strikes</option></select></div><div><label data-testid="alert-cooldown-label" htmlFor="alert-cooldown-input" className="text-[10px] uppercase tracking-wider text-slate-500">Cooldown seconds</label><input id="alert-cooldown-input" data-testid="alert-cooldown-input" type="number" min={0} max={3600} value={cooldownSeconds} onChange={(event) => setCooldownSeconds(Number(event.target.value))} className="mt-1.5 w-full rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 py-2 text-xs text-slate-300" /></div></div>
                <div className="grid grid-cols-2 gap-3"><div><label data-testid="quiet-start-label" htmlFor="quiet-start-input" className="text-[10px] uppercase tracking-wider text-slate-500">Quiet from</label><input id="quiet-start-input" data-testid="quiet-start-input" type="time" value={quietStart} onChange={(event) => setQuietStart(event.target.value)} className="mt-1.5 w-full rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 py-2 text-xs text-slate-300" /></div><div><label data-testid="quiet-end-label" htmlFor="quiet-end-input" className="text-[10px] uppercase tracking-wider text-slate-500">Quiet until</label><input id="quiet-end-input" data-testid="quiet-end-input" type="time" value={quietEnd} onChange={(event) => setQuietEnd(event.target.value)} className="mt-1.5 w-full rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 py-2 text-xs text-slate-300" /></div></div>
                <Button data-testid="alert-controls-save-button" type="submit" size="sm" className="w-full bg-[#1f2a41] text-slate-100 hover:bg-[#2a3856]" disabled={alertSettingsMutation.isPending}><Save className="mr-2 size-3.5" />{alertSettingsMutation.isPending ? "Saving…" : "Save alert controls"}</Button>
              </form></CardContent>
            </Card>

            <Card data-testid="claude-analyst-card" className="overflow-hidden border-[#315080]/60 bg-[#101621]/95 shadow-[0_16px_40px_rgba(28,74,135,0.12)]">
              <CardHeader className="flex-row items-center justify-between border-b border-[#202b42] px-4 py-3">
                <div className="flex items-center gap-2.5"><div data-testid="claude-analyst-icon" className="flex size-8 items-center justify-center rounded-md bg-blue-500/10 text-blue-300"><Bot className="size-4" /></div><div><CardTitle data-testid="claude-analyst-title" className="font-heading text-base text-slate-100">Claude AI analyst</CardTitle><p data-testid="claude-analyst-model" className="mt-0.5 text-[10px] text-slate-500">Haiku 4.5 · streaming · read-only</p></div></div>
                <Badge data-testid="claude-analyst-status" className={aiStatusQuery.data?.configured ? "border-blue-500/30 bg-blue-500/10 text-[10px] text-blue-300" : "border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300"}>{!aiStatusQuery.data?.configured ? "OFFLINE" : aiMutation.isPending ? "STREAMING" : "READY"}</Badge>
              </CardHeader>
              <CardContent className="space-y-3 p-4">
                <div data-testid="claude-action-grid" className="grid grid-cols-2 gap-2">
                  <Button data-testid="claude-explain-button" type="button" variant="outline" size="sm" className="justify-start border-[#2a364f] bg-[#0e131d] text-slate-300" onClick={() => aiMutation.mutate({ action: "explain" })} disabled={aiMutation.isPending}><Sparkles className="mr-2 size-3.5 text-blue-300" />Explain signal</Button>
                  <Button data-testid="claude-summary-button" type="button" variant="outline" size="sm" className="justify-start border-[#2a364f] bg-[#0e131d] text-slate-300" onClick={() => aiMutation.mutate({ action: "summary" })} disabled={aiMutation.isPending}><FileText className="mr-2 size-3.5 text-blue-300" />Daily summary</Button>
                  <Button data-testid="claude-alert-button" type="button" variant="outline" size="sm" className="justify-start border-amber-500/25 bg-amber-500/5 text-amber-200" onClick={() => aiMutation.mutate({ action: "alert" })} disabled={aiMutation.isPending}><Bell className="mr-2 size-3.5" />CE / PE alert</Button>
                  <Button data-testid="claude-notifications-button" type="button" variant="outline" size="sm" className="justify-start border-[#2a364f] bg-[#0e131d] text-slate-400" onClick={enableNotifications}><Bell className="mr-2 size-3.5" />Enable notify</Button>
                </div>
                <div data-testid="claude-output-panel" className="min-h-28 rounded-lg border border-[#202b42] bg-[#090d15] p-3">
                  <div className="flex items-center justify-between gap-2"><p data-testid="claude-output-label" className="text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-300/80">{aiAction === "alert" ? "Options alert" : aiAction === "summary" ? "Daily summary" : aiAction === "chat" ? "Chat response" : "Signal explanation"}</p>{modeLabel === "DEMO" && <Badge data-testid="claude-demo-badge" className="border-indigo-500/25 bg-indigo-500/10 text-[9px] text-indigo-300">DEMO INPUT</Badge>}</div>
                  <p data-testid="claude-output-text" className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{aiMutation.isPending && !aiOutput ? "Claude is reading the normalized option chain…" : aiOutput || "Choose an analysis action or ask a question about the current chain."}</p>
                </div>
                <form data-testid="claude-chat-form" className="space-y-2" onSubmit={(event) => { event.preventDefault(); const question = chatQuestion.trim(); if (question) aiMutation.mutate({ action: "chat", message: question }); }}>
                  <label data-testid="claude-chat-label" htmlFor="claude-chat-input" className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500"><MessageSquare className="size-3" />Ask about this chain</label>
                  <div className="flex gap-2"><Textarea id="claude-chat-input" data-testid="claude-chat-input" value={chatQuestion} onChange={(event) => setChatQuestion(event.target.value)} maxLength={1000} rows={2} placeholder="Why does the current OI favor CE, PE, or waiting?" className="min-h-16 resize-none border-[#2a364f] bg-[#0e131d] text-xs text-slate-200 placeholder:text-slate-600" /><Button data-testid="claude-chat-submit-button" type="submit" size="icon" className="h-16 w-11 shrink-0 bg-blue-600 text-white hover:bg-blue-500" disabled={aiMutation.isPending || !chatQuestion.trim()}><Send className="size-4" /></Button></div>
                </form>
                <p data-testid="claude-disclaimer" className="text-[10px] leading-relaxed text-slate-600">AI output is informational, may be wrong, and never places orders. Verify CE/PE alerts against live price, liquidity, and risk.</p>
              </CardContent>
            </Card>

            <Card data-testid="kotak-vault-card" className="border-[#202b42] bg-[#0e131d]/90"><CardContent className="p-4"><div className="flex items-start gap-3"><div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#e31837]/10 text-[#f04a63]"><LockKeyhole className="size-4" /></div><div className="min-w-0"><p data-testid="kotak-vault-title" className="text-sm font-semibold text-slate-200">Kotak Neo vault boundary</p><p data-testid="kotak-vault-message" className="mt-1 text-xs leading-relaxed text-slate-500">{authMessage}</p></div></div><Button data-testid="vault-connect-action" variant="outline" size="sm" className="mt-4 w-full border-[#2a364f] bg-transparent text-slate-300 hover:bg-[#171e2e]" onClick={() => setConnectOpen(true)}><KeyRound className="mr-2 size-3.5" />Review connection setup</Button></CardContent></Card>
          </div>
        </section>

        <footer data-testid="app-footer" className="flex flex-col gap-2 border-t border-[#1e2638] pt-4 text-[10px] text-slate-600 sm:flex-row sm:items-center sm:justify-between"><span data-testid="compliance-disclaimer">Read-only market analytics. Not investment advice. No orders are placed by this dashboard.</span><button data-testid="demo-mode-toggle" type="button" className="flex items-center gap-1 text-indigo-400 transition-colors hover:text-indigo-300" onClick={() => setDemoOpen(true)}><RefreshCw className="size-3" />Keep DEMO mode enabled</button></footer>
      </main>

      <Dialog open={connectOpen} onOpenChange={setConnectOpen}><DialogContent data-testid="kotak-modal-dialog" className="border-[#2a364f] bg-[#111622] text-slate-100 sm:max-w-lg"><DialogHeader><DialogTitle data-testid="kotak-modal-title" className="font-heading text-xl">Connect Kotak Neo</DialogTitle><DialogDescription data-testid="kotak-modal-description" className="text-slate-400">The current v2 login runs entirely in FastAPI. This browser never receives your Access Token, MPIN, TOTP secret, session token, sid, baseUrl, or feedUrl.</DialogDescription></DialogHeader><div className="space-y-4"><div data-testid="kotak-consumer-key-status" className="flex items-center justify-between rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-3"><div className="flex items-center gap-2"><Cloud className="size-4 text-amber-300" /><div><p data-testid="kotak-status-label" className="text-xs font-semibold text-slate-200">Server configuration</p><p data-testid="kotak-status-value" className="text-[11px] text-slate-500">{authQuery.data?.configured ? "Current v2 values detected" : "Awaiting backend/.env values"}</p></div></div><span data-testid="kotak-status-indicator" className={`size-2 rounded-full ${authQuery.data?.configured ? "bg-emerald-400" : "bg-amber-400"}`} /></div><details data-testid="kotak-credential-guide-accordion" className="group rounded-lg border border-[#202b42] bg-[#0e131d] p-3"><summary data-testid="kotak-credential-guide-summary" className="flex cursor-pointer list-none items-center justify-between text-xs font-semibold text-slate-300">Current v2 server-only setup<ChevronDown className="size-4 transition-transform group-open:rotate-180" /></summary><div className="mt-3 space-y-2 text-xs leading-relaxed text-slate-500"><p data-testid="kotak-credential-guide-copy">Add the current Kotak API Access Token, registered mobile, UCC, MPIN, TOTP secret, and a local application vault key to the backend environment. No broker credential is entered in this browser.</p><code data-testid="kotak-env-copy-snippet" className="block rounded-md border border-[#202b42] bg-[#07090e] p-3 font-mono text-[10px] leading-5 text-slate-400">KOTAK_MODE=LIVE<br />KOTAK_ACCESS_TOKEN=…<br />KOTAK_TOTP_SECRET=…<br />KOTAK_MPIN=…<br />KOTAK_MOBILE_NUMBER=…<br />KOTAK_UCC=…<br />KOTAK_VAULT_KEY=…</code></div></details></div><DialogFooter><Button data-testid="kotak-totp-login-btn" type="button" className="bg-[#e31837] text-white hover:bg-[#c8102e]" onClick={() => connectMutation.mutate()} disabled={connectMutation.isPending}>{connectMutation.isPending ? "Running server login…" : "Run server-side Kotak login"}</Button></DialogFooter></DialogContent></Dialog>

      <Dialog open={demoOpen} onOpenChange={setDemoOpen}><DialogContent data-testid="demo-confirm-dialog" className="border-indigo-500/30 bg-[#111622] text-slate-100 sm:max-w-md"><DialogHeader><DialogTitle data-testid="demo-confirm-title" className="font-heading text-xl">Stay in DEMO mode?</DialogTitle><DialogDescription data-testid="demo-confirm-description" className="text-slate-400">This dashboard will keep showing simulated normalized data until Kotak Neo credentials are configured server-side. It will never label simulated data as LIVE.</DialogDescription></DialogHeader><div data-testid="demo-confirm-warning" className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 px-3 py-3 text-xs leading-relaxed text-indigo-200">DEMO is an explicit fallback for preview and indicator testing only. No orders can be placed from this app.</div><DialogFooter><Button data-testid="demo-confirm-cancel-btn" variant="outline" className="border-[#2a364f] bg-transparent text-slate-300" onClick={() => setDemoOpen(false)}>Cancel</Button><Button data-testid="demo-confirm-accept-btn" className="bg-indigo-600 text-white hover:bg-indigo-500" onClick={() => demoMutation.mutate()} disabled={demoMutation.isPending}>{demoMutation.isPending ? "Confirming…" : "Confirm DEMO mode"}</Button></DialogFooter></DialogContent></Dialog>
    </div>
  );
}