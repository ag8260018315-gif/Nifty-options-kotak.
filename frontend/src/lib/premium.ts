import { ApiError } from "@/lib/api";

// Types mirror backend/routers/premium_market.py by hand. All of this is live Kotak data; nothing is simulated.

export type IndexSymbol4 = "NIFTY" | "BANKNIFTY" | "FINNIFTY" | "SENSEX";
export const PREMIUM_INDICES: IndexSymbol4[] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"];
export const INDEX_LABEL: Record<IndexSymbol4, string> = { NIFTY: "NIFTY 50", BANKNIFTY: "BANK NIFTY", FINNIFTY: "FIN NIFTY", SENSEX: "SENSEX" };
export type Interval = 1 | 5 | 15;

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
  ema9: Nums;
  ema21: Nums;
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
  candles: Candle[];
  series?: Series;
  atr?: number | null;
  levels: Levels | null;
  volume: VolumeInfo;
  trend: { label: string; basis: string[] };
  signal: Signal;
  disclaimer: string;
}

export interface Detail {
  label: string;
  symbol: string;
  name: string;
  quote: Quote | null;
  market: MarketInfo;
  analysis: Analysis;
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
  quote: Quote | null; // null until the first live (or last saved) price exists
  signal: QuickSignal;
}

export interface NewsItem {
  title: string;
  link: string;
  source: string | null;
  published_at: string | null;
}

export interface NewsBlock {
  status: "ok" | "unavailable";
  provider: string;
  items: NewsItem[];
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

export interface BreakoutResponse {
  count: number;
  stocks: BreakoutRow[];
  market: MarketInfo;
  method: string;
  accuracy: { validated: boolean; note: string };
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

// Poll quickly while prices can change; slowly when the market is closed.
export function pollMs(state: MarketInfo["state"] | undefined): number {
  return state === "CLOSED" || state === "NO_FEED" ? 30_000 : 2_500;
}
