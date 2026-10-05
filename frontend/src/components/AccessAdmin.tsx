import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import MoveData from "@/components/MoveData";
import PendingPayments from "@/components/billing/PendingPayments";
import { ApiError, apiGet, apiPost } from "@/lib/api";

export interface PendingRequest {
  email: string;
  name: string;
  note: string;
  created_at: number | null;
}

interface AccessUserRow {
  email: string;
  role: "admin" | "viewer" | "trial" | "subscriber" | "expired";
  source: "owner" | "render" | "approved" | "trial";
  trial_ends_at?: number | null;
}

function describe(person: AccessUserRow) {
  if (person.source === "owner") return "Owner";
  if (person.source === "render") return "Set in Render";
  if (person.source === "approved") return "Full access";
  const ends = person.trial_ends_at ? new Date(person.trial_ends_at * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "";
  return person.role === "trial" ? `Free trial, ends ${ends}` : `Trial ended ${ends}`;
}

interface PremiumRow {
  email: string;
  premium_until: number | null;
  active: boolean;
}

const fetchPremium = () => apiGet<PremiumRow[]>("/access/admin/premium");

export const fetchPendingRequests = () => apiGet<PendingRequest[]>("/access/admin/requests");
const fetchUsers = () => apiGet<AccessUserRow[]>("/access/admin/users");

function when(epochSeconds: number | null) {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

function problem(error: unknown) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
  }
  return "That didn't work. Try again.";
}

export default function AccessAdmin({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const requests = useQuery({ queryKey: ["access-requests"], queryFn: fetchPendingRequests, refetchInterval: 15_000, retry: false });
  const users = useQuery({ queryKey: ["access-users"], queryFn: fetchUsers, retry: false });
  const premiumList = useQuery({ queryKey: ["access-premium"], queryFn: fetchPremium, retry: false });
  const [premiumEmail, setPremiumEmail] = useState("");
  const [premiumDays, setPremiumDays] = useState(30);

  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const act = async (path: string, email: string, done: string) => {
    setWorking(`${path}:${email}`);
    setMessage(null);
    try {
      const result = await apiPost<{ emailed?: boolean }>(path, { email });
      setMessage(result.emailed === false ? `${done} The email to ${email} couldn't be sent, so let them know yourself.` : done);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["access-requests"] }),
        queryClient.invalidateQueries({ queryKey: ["access-users"] }),
      ]);
    } catch (error) {
      setMessage(problem(error));
    } finally {
      setWorking(null);
    }
  };

  const grantPremium = async () => {
    setWorking("premium-grant");
    setMessage(null);
    try {
      await apiPost("/access/admin/premium", { email: premiumEmail.trim(), days: premiumDays });
      setMessage(`Premium is on for ${premiumEmail.trim()} for ${premiumDays} days.`);
      setPremiumEmail("");
      await queryClient.invalidateQueries({ queryKey: ["access-premium"] });
    } catch (error) {
      setMessage(problem(error));
    } finally {
      setWorking(null);
    }
  };

  const revokePremium = async (email: string) => {
    setWorking(`premium-revoke:${email}`);
    try {
      await apiPost("/access/admin/premium/revoke", { email });
      setMessage(`Premium removed for ${email}.`);
      await queryClient.invalidateQueries({ queryKey: ["access-premium"] });
    } catch (error) {
      setMessage(problem(error));
    } finally {
      setWorking(null);
    }
  };

  const pending = requests.data ?? [];
  const people = users.data ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="access-admin-title">
      <button type="button" aria-label="Close access panel" onClick={onClose} className="absolute inset-0 cursor-default bg-black/50" />
      <div data-testid="access-admin-panel" className="relative flex h-full w-full max-w-md flex-col border-l border-[#202b42] bg-[#0c0f17] text-slate-200 shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#202b42] px-5 py-4">
          <div>
            <h2 id="access-admin-title" className="font-heading text-base font-semibold text-white">Access</h2>
            <p className="mt-0.5 text-xs text-slate-500">New sign-ups get a free trial automatically. Changes apply at once.</p>
          </div>
          <button ref={closeRef} type="button" data-testid="access-admin-close" onClick={onClose} className="rounded-md border border-[#26334b] px-3 py-1.5 text-xs text-slate-300 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">
            Close
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
          {message && <p data-testid="access-admin-message" role="status" className="rounded-lg border border-[#26334b] bg-[#131b2a] px-3 py-2 text-xs leading-relaxed text-slate-300">{message}</p>}

          <section aria-labelledby="pending-title">
            <h3 id="pending-title" className="text-sm font-semibold text-white">Waiting for approval {pending.length > 0 && <span className="ml-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-300">{pending.length}</span>}</h3>
            {requests.isError ? (
              <p className="mt-3 text-xs text-slate-500">{problem(requests.error)}</p>
            ) : pending.length === 0 ? (
              <p data-testid="access-no-requests" className="mt-3 text-xs text-slate-500">{requests.isLoading ? "Loading…" : "No requests right now. New ones also arrive in your Gmail."}</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {pending.map((item) => (
                  <li key={item.email} data-testid="access-request-row" className="rounded-lg border border-[#202b42] bg-[#090d15] p-3">
                    <p className="break-all text-sm text-white">{item.email}</p>
                    {(item.name || item.created_at) && <p className="mt-0.5 text-xs text-slate-500">{[item.name, when(item.created_at)].filter(Boolean).join(", ")}</p>}
                    {item.note && <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.note}</p>}
                    <div className="mt-3 flex gap-2">
                      <button type="button" data-testid="access-approve" disabled={working !== null} onClick={() => void act("/access/admin/approve", item.email, `Approved ${item.email}. They've been emailed.`)} className="h-8 rounded-md bg-emerald-500/90 px-3 text-xs font-semibold text-[#06120d] hover:bg-emerald-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/60 disabled:opacity-50">
                        {working === `/access/admin/approve:${item.email}` ? "Approving…" : "Approve"}
                      </button>
                      <button type="button" data-testid="access-decline" disabled={working !== null} onClick={() => void act("/access/admin/decline", item.email, `Declined ${item.email}.`)} className="h-8 rounded-md border border-[#26334b] px-3 text-xs text-slate-300 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50 disabled:opacity-50">
                        Decline
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <PendingPayments />
          <MoveData />
          <section aria-labelledby="premium-title" data-testid="premium-admin">
            <h3 id="premium-title" className="text-sm font-semibold text-white">Premium access</h3>
            <p className="mt-1 text-xs text-slate-500">Premium (live SENSEX, index charts and stock analysis) is separate from the free trial. Grant it after you receive payment.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <input data-testid="premium-email" type="email" value={premiumEmail} onChange={(event) => setPremiumEmail(event.target.value)} placeholder="email@example.com" aria-label="Email to give Premium" className="h-8 min-w-0 flex-1 rounded-md border border-[#2a364f] bg-[#0e131d] px-2.5 text-xs text-slate-200 placeholder:text-slate-600" />
              <select data-testid="premium-days" value={premiumDays} onChange={(event) => setPremiumDays(Number(event.target.value))} aria-label="Premium length" className="h-8 rounded-md border border-[#2a364f] bg-[#0e131d] px-2 text-xs text-slate-300">
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
                <option value={365}>1 year</option>
              </select>
              <button type="button" data-testid="premium-grant" disabled={working !== null || premiumEmail.trim().length < 3} onClick={() => void grantPremium()} className="h-8 rounded-md bg-amber-300 px-3 text-xs font-semibold text-[#1a1203] hover:bg-amber-200 disabled:opacity-50">Give Premium</button>
            </div>
            <ul className="mt-3 divide-y divide-[#1a2336] rounded-lg border border-[#202b42]">
              {(premiumList.data ?? []).map((row) => (
                <li key={row.email} data-testid="premium-row" className="flex items-center justify-between gap-3 px-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-slate-200">{row.email}</p>
                    <p className={`text-[11px] ${row.active ? "text-amber-300/90" : "text-slate-500"}`}>{row.active ? "Premium until" : "Premium ended"} {when(row.premium_until)}</p>
                  </div>
                  <button type="button" disabled={working !== null} onClick={() => void revokePremium(row.email)} className="h-7 shrink-0 rounded-md border border-[#26334b] px-2.5 text-[11px] text-slate-300 hover:bg-[#1a2336] disabled:opacity-50">Remove</button>
                </li>
              ))}
              {(premiumList.data ?? []).length === 0 && <li className="px-3 py-2.5 text-xs text-slate-500">{premiumList.isLoading ? "Loading…" : "Nobody has Premium yet."}</li>}
            </ul>
          </section>

          <section aria-labelledby="people-title">
            <h3 id="people-title" className="text-sm font-semibold text-white">People with access</h3>
            {users.isError ? (
              <p className="mt-3 text-xs text-slate-500">{problem(users.error)}</p>
            ) : (
              <ul className="mt-3 divide-y divide-[#1a2336] rounded-lg border border-[#202b42]">
                {people.map((person) => (
                  <li key={person.email} data-testid="access-user-row" className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-slate-200">{person.email}</p>
                      <p className={`text-[11px] ${person.role === "expired" ? "text-amber-300/80" : "text-slate-500"}`}>{describe(person)}</p>
                    </div>
                    <div className="flex shrink-0 gap-1.5">
                      {person.source === "trial" && (
                        <button type="button" data-testid="access-grant" disabled={working !== null} onClick={() => void act("/access/admin/approve", person.email, `Gave ${person.email} full access. They've been emailed.`)} className="h-7 shrink-0 rounded-md border border-emerald-500/30 px-2.5 text-[11px] text-emerald-300 hover:bg-emerald-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/50 disabled:opacity-50">
                          Give full access
                        </button>
                      )}
                      {(person.source === "approved" || (person.source === "trial" && person.role === "trial")) && (
                        <button type="button" data-testid="access-remove" disabled={working !== null} onClick={() => void act("/access/admin/remove", person.email, `Removed ${person.email}. They're signed out now.`)} className="h-7 shrink-0 rounded-md border border-rose-500/30 px-2.5 text-[11px] text-rose-300 hover:bg-rose-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/50 disabled:opacity-50">
                          Remove
                        </button>
                      )}
                    </div>
                  </li>
                ))}
                {people.length === 0 && <li className="px-3 py-2.5 text-xs text-slate-500">{users.isLoading ? "Loading…" : "Nobody yet."}</li>}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
