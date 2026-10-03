import { ApiError } from "@/lib/api";

// Types mirror backend/routers/premium_market.py by hand. All of this is live Kotak data; nothing is simulated.

export type IndexSymbol4 = "NIFTY" | "BANKNIFTY" | "FINNIFTY" | "SENSEX";
export const PREMIUM_INDICES: IndexSymbol4[] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"];
export const INDEX_LABEL: Record<IndexSymbol4, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY", FINNIFTY: "FIN NIFTY", SENSEX: "SENSEX" };
export type Interval = 1 | 5 | 15 | 30 | 60 | 240 | 1440 | 10080 | 43200;
export const INTERVAL_OPTIONS: { value: Interval; label: string }[] = [
  { value: 1, label: "1m" },
  { value: 5, label: "5m" },
  { value: 15, label: "15m" },
  { value: 30, label: "30m" },
  { value: 60, label: "1H" },
  { value: 240, label: "4H" },
  { value: 1440, label: "1D" },
  { value: 10080, label: "1W" },
  { value: 43200, label: "1M" },
];

export function intervalName(minutes: number): string {
  return ({ 1: "1-minute", 5: "5-minute", 15: "15-minute", 30: "30-minute", 60: "1-hour", 240: "4-hour", 1440: "daily", 10080: "weekly", 43200: "monthly" } as Record<number, string>)[minutes] ?? `${minutes}-minute`;
}

// Candle label: a clock time for intraday candles, a date for daily and weekly, both for hourly frames that span days.
export function stamp(epochSeconds: number, minutes: number): string {
  const date = new Date(epochSeconds * 1000);
  const day = date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "Asia/Kolkata" });
  if (minutes >= 43200) return date.toLocaleDateString("en-IN", { month: "short", year: "2-digit", timeZone: "Asia/Kolkata" });
  if (minutes >= 1440) return day;
  const time = clock(epochSeconds);
  return minutes >= 60 ? `${day} ${time}` : time;
}

export interface Quote {
  symbol: string;
  name: string;
  kind: string;
  ltp: number;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  volume: number | null;
  vwap?: number | null;
  updated_at: string;
}

export interface MarketInfo {
  state: "OPEN" | "DELAYED" | "CLOSED" | "NO_FEED";
  message: string;
  tick_age_seconds: number | null;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

type Nums = (number | null)[];

export interface Series {
  time: number[];
  ema_fast: Nums;
  ema_slow: Nums;
  rsi: Nums;
  macd: Nums;
  macd_signal: Nums;
  macd_hist: Nums;
  bb_upper: Nums;
  bb_mid: Nums;
  bb_lower: Nums;
  vwap: Nums;
}

export interface Levels {
  pivots: Record<string, number | null> | null;
  resistance: Nums;
  support: Nums;
  nearest_resistance: number | null;
  nearest_support: number | null;
  prev_day: Record<string, number | null> | null;
  day_high: number | null;
  day_low: number | null;
}

export interface VolumeInfo {
  available: boolean;
  note?: string;
  last?: number;
  average_20?: number | null;
  relative?: number | null;
  spike?: boolean;
  trend?: string;
  buying_pressure_pct?: number | null;
}

export type Action = "BUY" | "SELL" | "NEUTRAL" | "BUILDING";

export interface Signal {
  action: Action;
  score: number;
  strength?: string | null;
  reasons: string[];
  rsi?: number | null;
  price?: number | null;
  nearest_support?: number | null;
  nearest_resistance?: number | null;
}

export interface Analysis {
  interval: number;
  bars_total: number;
  bars_closed: number;
  bars_required: number;
  ema_periods?: [number, number];
  session_day?: string | null; // set when the market is closed and today has no candles: the day of the session shown instead
  history_available?: boolean;
  history_bars?: number;
  candles: Candle[];
  series?: Series;
  atr?: number | null;
  levels: Levels | null;
  volume: VolumeInfo;
  trend: { label: string; basis: string[] };
  signal: Signal;
  disclaimer: string;
}

export type Bias = "Bullish" | "Bearish" | "Neutral" | "Unavailable";
export type DataStatus = "LIVE" | "HISTORICAL" | "DELAYED" | "UNAVAILABLE";

export interface PatternHit {
  name: string;
  direction: "bullish" | "bearish" | "neutral";
  time: number;
  explanation: string;
}

export interface TradeSetup {
  direction: "LONG" | "SHORT";
  entry: number;
  entry_zone: [number, number];
  stop: number;
  targets: [number, number];
  risk_per_share: number;
  reward_to_risk: number;
  atr: number;
  zone_label: "Buy zone" | "Sell zone";
  method: string;
}

// The rules engine's verdict for one instrument. Confidence is signal strength, never a probability of winning.
export interface EngineSignal {
  generated_at: string;
  interval: number;
  disclaimer: string;
  bias: Bias;
  action: "BUY" | "SELL" | "NONE";
  score: number;
  confidence: { value: number; meaning: string };
  reasons: string[];
  patterns: PatternHit[];
  markers: PatternHit[];
  setup: TradeSetup | null;
  invalidation: string[];
  trend_strength: number | null;
  momentum: { value: number; label: string } | null;
  volatility: { atr_pct: number | null; label: string } | null;
  as_of_candle: number | null;
  data: { status: DataStatus; tick_age_seconds: number | null; message: string };
}

export interface PerformanceStats {
  trades?: number;
  wins?: number;
  win_rate_pct?: number;
  win_rate_ci95_pct?: [number, number];
  avg_r?: number;
  total_r?: number;
  profit_factor?: number | null;
  max_drawdown_r?: number;
  longest_losing_streak?: number;
  targets?: number;
  stops?: number;
  timeouts?: number;
  by_direction?: Record<"LONG" | "SHORT", { trades: number; win_rate_pct: number | null }>;
  period?: [string, string];
  reliable: boolean;
  note: string;
  created_at?: string;
  definition?: string;
  sessions?: number;
  stocks_tested?: number;
  rule?: { horizon_minutes: number; eval_step_minutes: number; cost_pct: number };
}

// Past results of this rule on stored history. `tested: false` means no number exists, and none is invented.
export type Performance = { tested: boolean; overall: PerformanceStats | null } & Partial<PerformanceStats>;

export interface Detail {
  label: string;
  symbol: string;
  name: string;
  sector?: string;
  quote: Quote | null;
  market: MarketInfo;
  analysis: Analysis;
  engine?: EngineSignal;
  performance?: Performance; // stocks only
}

export interface IndexRow {
  symbol: IndexSymbol4;
  name: string;
  quote: Quote | null;
  market: MarketInfo;
}

export interface QuickSignal {
  action: Action;
  score: number;
  strength: string | null;
  interval: number;
  trend: string;
  relative_volume: number | null;
  reasons: string[];
  nearest_support: number | null;
  nearest_resistance: number | null;
  bars_closed: number;
}

export interface StockRow {
  symbol: string;
  name: string;
  sector: string;
  quote: Quote | null; // null until the first live (or last saved) price exists
  signal: QuickSignal;
}

export interface StocksMeta {
  sectors: string[];
  stocks: { symbol: string; name: string; sector: string }[];
}

export interface StockNews {
  symbol: string;
  news: NewsBlock;
  note: string;
}

export type Watchlists = Record<string, string[]>;

export interface Layout {
  ema_fast: number;
  ema_slow: number;
  interval: Interval;
  pane: "rsi" | "macd" | "none";
  ema: boolean;
  bb: boolean;
  vwap: boolean;
  levels: boolean;
  patterns: boolean;
  setup: boolean;
}

export interface CompareRow {
  symbol: string;
  name: string;
  sector: string;
  quote: Quote | null;
  market: MarketInfo;
  bias: Bias;
  score: number;
  data_status: DataStatus;
  trend: string;
  rsi: number | null;
  volatility: { atr_pct: number | null; label: string } | null;
  relative_volume: number | null;
  change_over_window_pct: number | null;
  series: number[];
  times: number[];
}

export interface CompareResponse {
  interval: number;
  window_candles: number;
  stocks: CompareRow[];
  note: string;
}

export interface Sentiment {
  tone: "Positive" | "Negative" | "Mixed" | "Neutral";
  topic: string;
  positive_words: string[];
  negative_words: string[];
}

export interface SentimentSummary {
  counts: Record<Sentiment["tone"], number>;
  overall: Sentiment["tone"] | "None";
  items: number;
  note: string;
}

export interface NewsItem {
  title: string;
  link: string | null;
  source?: string | null;
  category?: string | null;
  published_at: string | null;
  sentiment?: Sentiment; // keyword reading, absent from older backends
}

export interface NewsBlock {
  status: "ok" | "unavailable";
  provider: string;
  items: NewsItem[];
  summary?: SentimentSummary;
}

export interface AnnouncementsResponse {
  symbol: string;
  announcements: NewsBlock;
  note: string;
}

export interface BreakoutSetup {
  score: number;
  distance_pct: number;
  resistance: number;
  support: number | null;
  relative_volume: number | null;
  buying_pressure_pct: number | null;
  trend: string | null;
  rsi: number | null;
  interval: number | null;
  reasons: string[];
}

export interface BreakoutRow {
  symbol: string;
  quote: Quote;
  setup: BreakoutSetup;
  news: NewsBlock;
}

export interface Comparison {
  test: string;
  listed_rate_pct: number | null;
  listed_setups: number;
  random_rate_pct: number | null;
  random_moments: number;
  difference_points: number;
  difference_ci95_points: [number, number];
  days: number;
  verdict: "BETTER" | "SAME" | "WORSE" | "UNKNOWN";
  verdict_text: string;
}

export interface Backtest {
  comparison?: Comparison | null;
  setups: number;
  successes: number;
  hit_rate_pct: number | null;
  ci95_low_pct: number | null;
  ci95_high_pct: number | null;
  stops: number;
  timeouts: number;
  sessions_tested: number;
  symbols_tested: number;
  period: [string, string] | null;
  by_score_band: { band: string; setups: number; hit_rate_pct: number | null }[];
  definition: string;
  created_at: string;
}

export interface BreakoutResponse {
  count: number;
  stocks: BreakoutRow[];
  market: MarketInfo;
  method: string;
  accuracy: { validated: boolean; note: string; backtest?: Backtest };
  news_note: string;
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return "";
  if (minutes < 60) return `${Math.max(1, minutes)} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`;
}

export interface PremiumStatus {
  live_mode: boolean;
  market: MarketInfo;
  sensex_subscribed: boolean;
  subscription_error: string | null;
  stocks_configured: number;
  stocks_with_prices: number;
  min_candles_for_signal: number;
  note: string;
}

const priceFormat = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const wholeFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function price(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : priceFormat.format(value);
}

export function whole(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : wholeFormat.format(value);
}

export function signed(value: number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${priceFormat.format(value)}${suffix}`;
}

export function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-slate-300";
  return value > 0 ? "text-emerald-300" : "text-rose-300";
}

export function clock(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

export function isPremiumRequired(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 403) return false;
  const detail = (error.body as { detail?: { code?: string } } | null)?.detail;
  return typeof detail === "object" && detail !== null && detail.code === "premium_required";
}

// The list rows carry the quick score-based action; show it with the same words the detail page uses.
export function biasFromAction(action: Action): Bias {
  return action === "BUY" ? "Bullish" : action === "SELL" ? "Bearish" : action === "NEUTRAL" ? "Neutral" : "Unavailable";
}

// "3 s ago", "2 min ago": how old the last price is, so a stale number can never pass as live.
export function tickAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "no price received yet";
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 120) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`;
}

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" }) + " IST";
}

// "Fri, 02 Oct" for an ISO date such as 2026-10-02.
export function sessionLabel(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00+05:30`);
  return Number.isNaN(date.getTime()) ? isoDate : date.toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", timeZone: "Asia/Kolkata" });
}

export const DEFAULT_EMA: [number, number] = [9, 20];

// Mirrors the server's rule for watchlist and layout names. A "/" or "." would also be read as part of the address, so they are refused here first.
export function checkName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "Give it a name first.";
  if (!/^[\p{L}\p{N}_ &-]{1,30}$/u.test(trimmed) || !/[\p{L}\p{N}]/u.test(trimmed)) return "Use letters, numbers, spaces and & - _ (up to 30 characters, with at least one letter or number).";
  return null;
}

// Mirrors the server's limits so a bad value is caught before a request is made.
export function validEma(fast: number, slow: number): string | null {
  if (!Number.isInteger(fast) || !Number.isInteger(slow)) return "Use whole numbers.";
  if (fast < 2 || fast > 100) return "Fast EMA must be 2 to 100.";
  if (slow < 3 || slow > 300) return "Slow EMA must be 3 to 300.";
  if (slow <= fast) return "Slow EMA must be longer than fast EMA.";
  return null;
}

// Poll quickly while prices can change; slowly when the market is closed.
export function pollMs(state: MarketInfo["state"] | undefined): number {
  return state === "CLOSED" || state === "NO_FEED" ? 30_000 : 2_500;
}
