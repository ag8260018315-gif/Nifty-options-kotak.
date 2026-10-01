// Risk checks to run through before placing an order in your broker app.
// They use only the live data already on the dashboard plus numbers you type in. They describe
// risk. They never say whether to trade, and this dashboard never places orders.

export type CheckStatus = "flag" | "clear" | "note";

export interface CheckResult {
  id: string;
  title: string;
  status: CheckStatus;
  detail: string;
}

export interface Leg {
  ltp: number;
  oi: number;
  iv: number;
  delta: number;
  theta?: number | null;
  volume?: number | null;
}

export interface ChainRow {
  strike: number;
  is_atm: boolean;
  call: Leg;
  put: Leg;
}

export interface Inputs {
  capital: number | null;
  riskPct: number | null;
  lotSize: number | null;
  lots: number | null;
  limitPrice: number | null;
}

export interface Sizing {
  price: number;
  perLot: number;
  cost: number;
  costPctOfCapital: number | null;
  riskBudget: number | null;
  lotsAllowed: number | null;
  withinBudget: boolean | null;
}

export interface CheckInput {
  rows: ChainRow[];
  strike: number | null;
  side: "CE" | "PE";
  feedState: string;
  lastTickMs: number | null;
  nowMs: number;
  expiry: string | undefined;
  inputs: Inputs;
}

export const MANUAL_ITEMS: { id: string; text: string }[] = [
  { id: "exit", text: "I have decided my maximum loss and my exit plan (a price or a time) before entering." },
  { id: "ticket", text: "I will double-check the order ticket: index, expiry, strike, CE or PE, quantity and price." },
  { id: "limit", text: "I am using a limit order, not a market order." },
  { id: "funds", text: "I have checked that I have enough funds or margin in my broker account. This dashboard can't see it." },
  { id: "events", text: "I have checked today's events: RBI, results, global markets and news." },
  { id: "calm", text: "I am not trading to win back a loss, and I am calm." },
];

const MONTHS: Record<string, number> = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
const OPENING_END = 9 * 60 + 30;
const SESSION_OPEN = 9 * 60 + 15;
const CLOSING_START = 15 * 60 + 15;
const SESSION_CLOSE = 15 * 60 + 30;
const STALE_AFTER_SECONDS = 15;
const THIN_OI_RATIO = 0.25;
const FAR_OTM_DELTA = 0.2;
const DEEP_ITM_DELTA = 0.85;
const FAST_DECAY_PCT = 8;
const PRICE_MISMATCH_PCT = 3;

export function istClock(ms: number) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Kolkata", weekday: "short", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", hour12: false }).formatToParts(new Date(ms));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return { weekday: get("weekday"), minutes: (Number(get("hour")) % 24) * 60 + Number(get("minute")), year: Number(get("year")), month: Number(get("month")), day: Number(get("day")) };
}

export function daysToExpiry(expiry: string | undefined, nowMs: number): number | null {
  const match = (expiry ?? "").trim().match(/^(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\s+(\d{4})$/);
  if (!match) return null;
  const month = MONTHS[(match[2] ?? "").toLowerCase()];
  if (month === undefined) return null;
  const today = istClock(nowMs);
  const target = Date.UTC(Number(match[3]), month, Number(match[1]));
  const now = Date.UTC(today.year, today.month - 1, today.day);
  return Math.round((target - now) / 86_400_000);
}

const money = (value: number, digits = 0) => value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

function sessionCheck(nowMs: number, feedState: string): CheckResult {
  const { weekday, minutes } = istClock(nowMs);
  const weekend = weekday === "Sat" || weekday === "Sun";
  const base = { id: "session", title: "Market session" };
  if (weekend || minutes < SESSION_OPEN || minutes >= SESSION_CLOSE) {
    return { ...base, status: "flag", detail: "The market is closed (NSE trades 09:15 to 15:30 IST, Monday to Friday). The prices shown are the latest available, not live." };
  }
  if (feedState === "MARKET_CLOSED") {
    return { ...base, status: "flag", detail: "The feed reports the market as closed. It may be a holiday. Check the exchange calendar." };
  }
  if (minutes < OPENING_END) {
    return { ...base, status: "flag", detail: "It is the first 15 minutes after the open. Prices can swing sharply and gaps between bid and ask prices are often wide." };
  }
  if (minutes >= CLOSING_START) {
    return { ...base, status: "flag", detail: "It is the last 15 minutes before the close. Prices can move sharply and orders may be filled at worse prices." };
  }
  return { ...base, status: "clear", detail: "The market is open and it is not the opening or closing 15 minutes." };
}

function freshnessCheck(feedState: string, lastTickMs: number | null, nowMs: number): CheckResult {
  const base = { id: "freshness", title: "Data freshness" };
  if (feedState !== "LIVE") {
    const label = feedState === "MARKET_CLOSED" ? "market closed" : feedState === "STALE" ? "delayed" : feedState === "EXPIRED" ? "session expired" : feedState.toLowerCase();
    return { ...base, status: "flag", detail: `The feed is ${label}. Do not rely on these prices; check the live price in your broker app.` };
  }
  if (lastTickMs === null) return { ...base, status: "note", detail: "The feed is live but the time of the last update isn't available." };
  const age = Math.max(0, Math.round((nowMs - lastTickMs) / 1000));
  if (age > STALE_AFTER_SECONDS) return { ...base, status: "flag", detail: `The last update was ${age} seconds ago, so these prices may be out of date.` };
  return { ...base, status: "clear", detail: `The feed is live. The last update was ${age} seconds ago.` };
}

function median(values: number[]): number | null {
  const sorted = values.filter((value) => value > 0).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[mid] as number) : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

export function sizingFor(ltp: number, inputs: Inputs): Sizing | null {
  const { capital, riskPct, lotSize, lots, limitPrice } = inputs;
  if (!lotSize || !lots || lotSize <= 0 || lots <= 0) return null;
  const price = limitPrice && limitPrice > 0 ? limitPrice : ltp;
  const perLot = price * lotSize;
  const cost = perLot * lots;
  const riskBudget = capital && riskPct && capital > 0 && riskPct > 0 ? (capital * riskPct) / 100 : null;
  return {
    price,
    perLot,
    cost,
    costPctOfCapital: capital && capital > 0 ? (cost / capital) * 100 : null,
    riskBudget,
    lotsAllowed: riskBudget !== null && perLot > 0 ? Math.floor(riskBudget / perLot) : null,
    withinBudget: riskBudget !== null ? cost <= riskBudget : null,
  };
}

export function evaluate(input: CheckInput): { checks: CheckResult[]; sizing: Sizing | null; ltp: number | null } {
  const { rows, strike, side, feedState, lastTickMs, nowMs, expiry, inputs } = input;
  const checks: CheckResult[] = [sessionCheck(nowMs, feedState), freshnessCheck(feedState, lastTickMs, nowMs)];
  const sorted = [...rows].sort((a, b) => a.strike - b.strike);
  const index = sorted.findIndex((row) => row.strike === strike);
  const row = index >= 0 ? sorted[index] : undefined;
  if (!row) {
    checks.push({ id: "contract", title: "Contract", status: "note", detail: sorted.length ? "Pick a strike and CE or PE to run the contract checks." : "Waiting for the live option chain." });
    return { checks, sizing: null, ltp: null };
  }
  const leg = side === "CE" ? row.call : row.put;
  const label = `${row.strike} ${side}`;

  checks.push(
    leg.ltp > 0
      ? { id: "contract", title: "Contract", status: "clear", detail: `${label}: last traded price ₹${money(leg.ltp, 2)}.` }
      : { id: "contract", title: "Contract", status: "flag", detail: `${label} has no valid last traded price right now.` },
  );

  const typicalOi = median(sorted.map((item) => (side === "CE" ? item.call.oi : item.put.oi)));
  const volume = leg.volume;
  if (volume === null || volume === undefined) {
    checks.push({ id: "liquidity", title: "Liquidity", status: "note", detail: `Volume isn't available for ${label}. Open interest is ${money(leg.oi)}. Check the number of buyers and sellers in your broker app.` });
  } else if (volume <= 0) {
    checks.push({ id: "liquidity", title: "Liquidity", status: "flag", detail: `No trades are recorded today at ${label}, so it may be hard to get a fair price.` });
  } else if (typicalOi !== null && leg.oi < typicalOi * THIN_OI_RATIO) {
    checks.push({ id: "liquidity", title: "Liquidity", status: "flag", detail: `Open interest at ${label} (${money(leg.oi)}) is thin compared with nearby strikes (typically about ${money(typicalOi)}). Volume today is ${money(volume)}.` });
  } else {
    checks.push({ id: "liquidity", title: "Liquidity", status: "clear", detail: `Volume today is ${money(volume)} and open interest is ${money(leg.oi)}, which is in line with nearby strikes.` });
  }

  checks.push({ id: "spread", title: "Bid-ask gap", status: "note", detail: "This dashboard doesn't show the best bid and ask prices (the highest price a buyer offers and the lowest price a seller wants). Look at them on your broker's order ticket, because a wide gap is a hidden cost." });

  const atmIndex = sorted.findIndex((item) => item.is_atm);
  const away = atmIndex >= 0 ? Math.abs(index - atmIndex) : null;
  const delta = Math.abs(leg.delta);
  if (delta < FAR_OTM_DELTA) {
    checks.push({ id: "distance", title: "Distance from the index price", status: "flag", detail: `${label} is far out of the money${away !== null ? ` (${away} strikes from ATM)` : ""}, with a delta of ${delta.toFixed(2)}. It needs a large move to gain value and can lose value quickly.` });
  } else if (delta > DEEP_ITM_DELTA) {
    checks.push({ id: "distance", title: "Distance from the index price", status: "note", detail: `${label} is deep in the money (delta ${delta.toFixed(2)}). It moves almost like the index and costs more per lot.` });
  } else {
    checks.push({ id: "distance", title: "Distance from the index price", status: "clear", detail: `${label} has a delta of ${delta.toFixed(2)}${away !== null ? `, ${away} strikes from ATM` : ""}.` });
  }

  const days = daysToExpiry(expiry, nowMs);
  if (days === null) {
    checks.push({ id: "expiry", title: "Time to expiry", status: "note", detail: "The expiry date isn't available. Check it on your order ticket." });
  } else if (days <= 0) {
    checks.push({ id: "expiry", title: "Time to expiry", status: "flag", detail: `This contract expires today (${expiry}). Time decay is extreme, prices can swing sharply, and it can expire worthless.` });
  } else if (days === 1) {
    checks.push({ id: "expiry", title: "Time to expiry", status: "flag", detail: `This contract expires tomorrow (${expiry}). Time decay is very fast.` });
  } else {
    checks.push({ id: "expiry", title: "Time to expiry", status: "clear", detail: `${days} days to expiry (${expiry}).` });
  }

  if (leg.theta === null || leg.theta === undefined || leg.ltp <= 0) {
    checks.push({ id: "decay", title: "Time decay", status: "note", detail: "A time decay estimate isn't available for this contract." });
  } else {
    const perDay = Math.abs(leg.theta);
    const pct = (perDay / leg.ltp) * 100;
    const text = `Time passing alone may take about ₹${money(perDay, 2)} (${pct.toFixed(1)}%) off the price each day, other things equal (model estimate).`;
    checks.push({ id: "decay", title: "Time decay", status: pct >= FAST_DECAY_PCT ? "flag" : "clear", detail: text });
  }

  checks.push({ id: "iv", title: "Implied volatility", status: "note", detail: `Implied volatility here is about ${leg.iv.toFixed(1)}% (model estimate). When it is high, options cost more, and if it falls after you enter, the price can drop even if the index doesn't move.` });

  if (inputs.limitPrice && inputs.limitPrice > 0 && leg.ltp > 0) {
    const diff = ((inputs.limitPrice - leg.ltp) / leg.ltp) * 100;
    checks.push(
      Math.abs(diff) > PRICE_MISMATCH_PCT
        ? { id: "price", title: "Your price against the last traded price", status: "flag", detail: `Your price ₹${money(inputs.limitPrice, 2)} is ${Math.abs(diff).toFixed(1)}% ${diff > 0 ? "above" : "below"} the last traded price ₹${money(leg.ltp, 2)}. Check for a typing mistake.` }
        : { id: "price", title: "Your price against the last traded price", status: "clear", detail: `Your price ₹${money(inputs.limitPrice, 2)} is within ${PRICE_MISMATCH_PCT}% of the last traded price ₹${money(leg.ltp, 2)}.` },
    );
  } else {
    checks.push({ id: "price", title: "Your price against the last traded price", status: "note", detail: "Enter the price you plan to use below, to compare it with the last traded price." });
  }

  const sizing = sizingFor(leg.ltp, inputs);
  if (!sizing) {
    checks.push({ id: "size", title: "Position size against your risk limit", status: "note", detail: "Enter your capital, the most you accept to lose on one trade, the lot size and the number of lots below." });
  } else if (sizing.withinBudget === null) {
    checks.push({ id: "size", title: "Position size against your risk limit", status: "note", detail: `Premium at risk is ₹${money(sizing.cost)}. Enter your capital and risk limit to compare.` });
  } else if (!sizing.withinBudget) {
    checks.push({ id: "size", title: "Position size against your risk limit", status: "flag", detail: `The premium at risk, ₹${money(sizing.cost)}, is above your own limit of ₹${money(sizing.riskBudget ?? 0)}. Your limit allows ${sizing.lotsAllowed ?? 0} lot(s) at this price.` });
  } else {
    checks.push({ id: "size", title: "Position size against your risk limit", status: "clear", detail: `The premium at risk, ₹${money(sizing.cost)}, is within your own limit of ₹${money(sizing.riskBudget ?? 0)}.` });
  }
  return { checks, sizing, ltp: leg.ltp };
}
