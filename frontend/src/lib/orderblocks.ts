// Candle pattern markers ("order block" style).
//
// What a marker is: the last candle that moved against a move that followed it. A down candle that is
// followed within a few candles by an up-move much larger than a normal candle, or the reverse.
// What it is NOT: it is not order data. It says nothing about who traded or what orders exist, and it is
// not a recommendation. It marks where a pattern happened on candles that have already closed.
//
// Nothing is invented. Every marker is computed from the candles supplied, by fixed rules:
//   size    the move after the candle must be at least IMPULSE_ATR x the average candle range (ATR, 14 candles)
//   window  the move must happen within LOOKAHEAD candles
//   status  tracked live against later candles: not revisited, revisited, or closed through

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export type MarkerKind = "up-move" | "down-move"; // what followed the marked candle
export type MarkerStatus = "not-revisited" | "revisited" | "closed-through";

export interface Marker {
  id: number; // 1 is the most recent
  kind: MarkerKind;
  index: number;
  time: number;
  high: number;
  low: number;
  moveAtr: number;
  movePoints: number;
  status: MarkerStatus;
  endIndex: number | null; // the candle that closed through it, if any
  candlesAgo: number;
  side: "above" | "below" | "inside"; // where the latest close sits relative to the marked range
  distancePoints: number; // 0 when inside
}

export interface Detection {
  ready: boolean;
  reason: string | null;
  atr: number | null;
  markers: Marker[];
}

export interface Options {
  atrPeriod: number;
  impulseAtr: number;
  lookahead: number;
  maxMarkers: number;
  minCandles: number;
}

export const DEFAULTS: Options = { atrPeriod: 14, impulseAtr: 1.5, lookahead: 3, maxMarkers: 6, minCandles: 20 };

function trueRange(candles: Candle[], index: number): number {
  const candle = candles[index] as Candle;
  const previous = index > 0 ? (candles[index - 1] as Candle) : null;
  if (!previous) return candle.high - candle.low;
  return Math.max(candle.high - candle.low, Math.abs(candle.high - previous.close), Math.abs(candle.low - previous.close));
}

/** Average candle range over the `period` candles ending at `index`; null until there are enough candles. */
export function atrAt(candles: Candle[], index: number, period = DEFAULTS.atrPeriod): number | null {
  if (index < period - 1 || index >= candles.length) return null;
  let total = 0;
  for (let i = index - period + 1; i <= index; i++) total += trueRange(candles, i);
  return total / period;
}

export function detectMarkers(candles: Candle[], overrides: Partial<Options> = {}): Detection {
  const options = { ...DEFAULTS, ...overrides };
  const count = candles.length;
  if (count < options.minCandles) {
    return { ready: false, reason: `Needs at least ${options.minCandles} candles (${count} so far).`, atr: null, markers: [] };
  }
  const found: Omit<Marker, "id" | "candlesAgo" | "side" | "distancePoints">[] = [];
  for (let i = options.atrPeriod - 1; i < count - 1; i++) {
    const candle = candles[i] as Candle;
    const next = candles[i + 1] as Candle;
    const atr = atrAt(candles, i, options.atrPeriod);
    if (atr === null || atr <= 0) continue;
    const windowEnd = Math.min(count - 1, i + options.lookahead);
    let kind: MarkerKind | null = null;
    let movePoints = 0;
    if (candle.close < candle.open && next.close > next.open) {
      let best = -Infinity;
      for (let j = i + 1; j <= windowEnd; j++) best = Math.max(best, (candles[j] as Candle).close);
      movePoints = best - candle.high;
      if (movePoints >= options.impulseAtr * atr) kind = "up-move";
    } else if (candle.close > candle.open && next.close < next.open) {
      let best = Infinity;
      for (let j = i + 1; j <= windowEnd; j++) best = Math.min(best, (candles[j] as Candle).close);
      movePoints = candle.low - best;
      if (movePoints >= options.impulseAtr * atr) kind = "down-move";
    }
    if (!kind) continue;

    let status: MarkerStatus = "not-revisited";
    let endIndex: number | null = null;
    for (let k = i + options.lookahead + 1; k < count; k++) {
      const later = candles[k] as Candle;
      const closedThrough = kind === "up-move" ? later.close < candle.low : later.close > candle.high;
      if (closedThrough) {
        status = "closed-through";
        endIndex = k;
        break;
      }
      if (later.low <= candle.high && later.high >= candle.low) status = "revisited";
    }
    found.push({ kind, index: i, time: candle.time, high: candle.high, low: candle.low, moveAtr: movePoints / atr, movePoints, status, endIndex });
  }

  const lastClose = (candles[count - 1] as Candle).close;
  const markers = found
    .sort((a, b) => b.index - a.index)
    .slice(0, options.maxMarkers)
    .map((marker, position): Marker => {
      const side = lastClose > marker.high ? "above" : lastClose < marker.low ? "below" : "inside";
      const distancePoints = side === "above" ? lastClose - marker.high : side === "below" ? marker.low - lastClose : 0;
      return { ...marker, id: position + 1, candlesAgo: count - 1 - marker.index, side, distancePoints };
    });
  return { ready: true, reason: null, atr: atrAt(candles, count - 1, options.atrPeriod), markers };
}
