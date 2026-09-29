import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiGet, apiPost } from "@/lib/api";

export interface PendingRequest {
  email: string;
  name: string;
  note: string;
  created_at: number | null;
}

interface AccessUserRow {
  email: string;
  role: "admin" | "viewer";
  source: "owner" | "render" | "approved";
}

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

  const pending = requests.data ?? [];
  const people = users.data ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="access-admin-title">
      <button type="button" aria-label="Close access panel" onClick={onClose} className="absolute inset-0 cursor-default bg-black/50" />
      <div data-testid="access-admin-panel" className="relative flex h-full w-full max-w-md flex-col border-l border-[#202b42] bg-[#0c0f17] text-slate-200 shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#202b42] px-5 py-4">
          <div>
            <h2 id="access-admin-title" className="font-heading text-base font-semibold text-white">Access</h2>
            <p className="mt-0.5 text-xs text-slate-500">Approve who can sign in. Changes apply at once.</p>
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
                      <p className="text-[11px] text-slate-500">{person.source === "owner" ? "Owner" : person.source === "render" ? "Set in Render" : "Approved here"}</p>
                    </div>
                    {person.source === "approved" && (
                      <button type="button" data-testid="access-remove" disabled={working !== null} onClick={() => void act("/access/admin/remove", person.email, `Removed ${person.email}. They're signed out now.`)} className="h-7 shrink-0 rounded-md border border-rose-500/30 px-2.5 text-[11px] text-rose-300 hover:bg-rose-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/50 disabled:opacity-50">
                        Remove
                      </button>
                    )}
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
