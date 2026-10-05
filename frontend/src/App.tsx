import { Link, Routes, Route } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { useState } from "react";

import AccessAdmin, { fetchPendingRequests } from "@/components/AccessAdmin";
import Home from "@/pages/Home";
import Exchange from "@/pages/Exchange";
import Premium from "@/pages/Premium";
import Subscription from "@/pages/Subscription";
import PlanBanner from "@/components/billing/PlanBanner";
import { fetchOrders } from "@/components/billing/PendingPayments";
import Landing from "@/pages/Landing";
import Upgrade from "@/pages/Upgrade";
import { ApiError, apiGet, apiPost } from "@/lib/api";

interface AccessUser {
  auth_required: boolean;
  email: string | null;
  role: "admin" | "viewer" | "trial" | "subscriber" | "expired";
  trial_ends_at?: number | null;
  premium?: boolean;
  premium_until?: number | null;
}

const OPEN_ACCESS: AccessUser = { auth_required: false, email: null, role: "admin", premium: true };

// null = signed out. A backend without the sign-in routes (404) is treated as open, like before.
async function fetchAccess(): Promise<AccessUser | null> {
  try {
    return await apiGet<AccessUser>("/access/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    if (error instanceof ApiError && error.status === 404) return OPEN_ACCESS;
    throw error;
  }
}

function Splash() {
  return (
    <div data-testid="access-loading" className="flex min-h-screen items-center justify-center bg-[#080c14]">
      <div className="flex size-10 items-center justify-center rounded-lg bg-[#e0314b] text-white motion-safe:animate-pulse">
        <Activity className="size-5" />
      </div>
    </div>
  );
}

function Unreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <div data-testid="access-unreachable" className="flex min-h-screen items-center justify-center bg-[#080c14] px-6 text-center">
      <div className="max-w-sm">
        <p className="font-heading text-lg font-semibold text-[#e6ebf4]">Can't reach the server</p>
        <p className="mt-2 text-sm leading-relaxed text-[#8c98ae]">The dashboard backend didn't answer. It may be restarting; this usually takes a minute.</p>
        <button type="button" onClick={onRetry} className="mt-6 h-10 rounded-lg bg-[#e6ebf4] px-5 text-sm font-semibold text-[#080c14] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e6ebf4]/60">
          Try again
        </button>
      </div>
    </div>
  );
}

function useSignOut() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const signOut = async () => {
    setBusy(true);
    try {
      await apiPost("/access/logout");
    } catch {
      // Signing out locally still hides the dashboard; the cookie expires on its own.
    }
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "access-me" });
    queryClient.setQueryData(["access-me"], null);
    setBusy(false);
  };
  return { busy, signOut };
}

function trialDaysLeft(endsAt: number | null | undefined) {
  if (!endsAt) return null;
  return Math.max(0, Math.ceil((endsAt * 1000 - Date.now()) / 86_400_000));
}

function SignedInBar({ user }: { user: AccessUser }) {
  const { busy, signOut } = useSignOut();
  const [panelOpen, setPanelOpen] = useState(false);
  const isOwner = user.role === "admin";
  const pending = useQuery({ queryKey: ["access-requests"], queryFn: fetchPendingRequests, refetchInterval: 60_000, retry: false, enabled: isOwner });
  const orders = useQuery({ queryKey: ["billing-orders"], queryFn: fetchOrders, refetchInterval: 60_000, retry: false, enabled: isOwner });
  const pendingCount = (pending.data?.length ?? 0) + (orders.data?.orders.length ?? 0);
  const daysLeft = user.role === "trial" ? trialDaysLeft(user.trial_ends_at) : null;
  return (
    <>
    <div data-testid="signed-in-bar" className="fixed bottom-4 left-4 z-40 flex items-center gap-3 rounded-full border border-[#202b42] bg-[#0c0f17]/95 py-1.5 pl-4 pr-1.5 text-xs text-slate-400 shadow-lg backdrop-blur">
      <span className="max-w-[40vw] truncate">{user.email}</span>
      {isOwner && <span className="rounded-full bg-[#1f2a41] px-2 py-0.5 text-[10px] text-slate-300">Owner</span>}
      {!isOwner && !user.premium && user.role === "subscriber" && <span data-testid="standard-badge" className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">Standard</span>}
      {!isOwner && !user.premium && <Link to="/subscription" data-testid="upgrade-button" className="rounded-full bg-amber-300 px-3 py-1 text-[11px] font-bold text-[#1a1203] hover:bg-amber-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200/60">Upgrade to Premium</Link>}
      {!isOwner && <Link to="/subscription" data-testid="plans-link" className="rounded-full border border-[#26334b] px-3 py-1 text-slate-200 hover:bg-[#1a2336]">Plan</Link>}
      {!isOwner && user.premium && <span data-testid="premium-badge" className="rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300">Premium</span>}
      {daysLeft !== null && (
        <span data-testid="trial-badge" title="Your free trial ends automatically. Nothing is charged." className="rounded-full border border-emerald-400/25 bg-emerald-400/[0.08] px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
          Free trial: {daysLeft === 0 ? "ends today" : `${daysLeft} ${daysLeft === 1 ? "day" : "days"} left`}
        </span>
      )}
      {isOwner && (
        <button type="button" data-testid="open-access-panel" onClick={() => setPanelOpen(true)} className="flex items-center gap-1.5 rounded-full border border-[#26334b] px-3 py-1 text-slate-200 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50">
          Access
          {pendingCount > 0 && <span data-testid="pending-count" className="rounded-full bg-amber-400 px-1.5 text-[10px] font-bold text-[#1a1203]">{pendingCount}</span>}
        </button>
      )}
      <button type="button" data-testid="sign-out" disabled={busy} onClick={() => void signOut()} className="rounded-full border border-[#26334b] px-3 py-1 text-slate-200 hover:bg-[#1a2336] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/50 disabled:opacity-50">
        Sign out
      </button>
    </div>
    {panelOpen && <AccessAdmin onClose={() => setPanelOpen(false)} />}
    </>
  );
}

function ExpiredTrial({ user }: { user: AccessUser }) {
  const queryClient = useQueryClient();
  const { signOut } = useSignOut();
  return <Upgrade email={user.email} onSignOut={() => void signOut()} onApproved={() => void queryClient.invalidateQueries({ queryKey: ["access-me"] })} />;
}

function AccessGate({ page = "home" }: { page?: "home" | "premium" | "exchange" | "subscription" }) {
  const queryClient = useQueryClient();
  const access = useQuery({ queryKey: ["access-me"], queryFn: fetchAccess, refetchInterval: 60_000, retry: 1 });

  if (access.isPending) return <Splash />;
  if (access.isError) return <Unreachable onRetry={() => void access.refetch()} />;
  if (access.data === null) {
    return <Landing onSignedIn={() => void queryClient.invalidateQueries({ queryKey: ["access-me"] })} />;
  }
  if (access.data.role === "expired") return <ExpiredTrial user={access.data} />;
  return (
    <>
      {access.data.auth_required && access.data.email && <PlanBanner />}
      {page === "subscription" ? <Subscription email={access.data.email} /> : page === "exchange" ? <Exchange /> : page === "premium" ? <Premium user={{ email: access.data.email, premium: access.data.premium === true, premium_until: access.data.premium_until }} /> : <Home isOwner={access.data.role === "admin"} />}
      {access.data.auth_required && access.data.email && <SignedInBar user={access.data} />}
    </>
  );
}

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AccessGate />} />
      <Route path="/subscription" element={<AccessGate page="subscription" />} />
      <Route path="/exchange" element={<AccessGate page="exchange" />} />
      <Route path="/premium" element={<AccessGate page="premium" />} />
      <Route path="/premium/stocks" element={<AccessGate page="premium" />} />
      <Route path="/premium/stocks/:symbol" element={<AccessGate page="premium" />} />
      <Route path="/premium/sectors" element={<AccessGate page="premium" />} />
      <Route path="/premium/alerts" element={<AccessGate page="premium" />} />
      <Route path="/premium/compare" element={<AccessGate page="premium" />} />
    </Routes>
  );
}
