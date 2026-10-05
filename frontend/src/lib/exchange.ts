import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";

// Trader's Exchange: a notice board for services. Everything is read and written through /api/exchange/*.

export interface ExchangeMeta {
  categories: Record<string, string>;
  rules: string[];
  note: string;
  display_name: string | null;
  unread: number;
  is_owner: boolean;
  pending?: number;
  max_listings: number;
}

export interface Listing {
  id: string;
  title: string;
  category: string;
  category_label: string;
  description: string;
  price_text: string;
  seller_name: string;
  created_at: number;
  mine: boolean;
  status?: "pending" | "approved" | "rejected" | "paused" | "hidden";
  note?: string;
  reports?: number;
  reasons?: string[];
}

export interface ThreadMessage {
  mine: boolean;
  text: string;
  at: number;
}

export interface Thread {
  id: string;
  listing_id: string;
  listing_title: string;
  role: "buyer" | "seller";
  other_name: string;
  last_at: number;
  unread: number;
  messages: ThreadMessage[];
}

export interface Queue {
  pending: Listing[];
  reported: Listing[];
}

export interface ListingForm {
  title: string;
  category: string;
  description: string;
  price_text: string;
  accept: boolean;
}

export const STATUS_TEXT: Record<NonNullable<Listing["status"]>, string> = {
  pending: "Waiting for the owner's approval",
  approved: "Live",
  rejected: "Not accepted",
  paused: "Paused (hidden)",
  hidden: "Hidden after reports, being reviewed",
};

export function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (error.status === 429) return "You're doing that a lot. Please wait a while and try again.";
  }
  return "That didn't go through. Try again shortly.";
}

export function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

export function useExchangeMeta() {
  return useQuery({ queryKey: ["ex-meta"], queryFn: () => apiGet<ExchangeMeta>("/exchange/meta"), refetchInterval: 30_000, retry: false });
}

export function useListings(category: string, q: string) {
  return useQuery({
    queryKey: ["ex-listings", category, q],
    queryFn: () => apiGet<{ listings: Listing[]; note: string }>(`/exchange/listings?category=${encodeURIComponent(category)}&q=${encodeURIComponent(q)}`),
    retry: false,
  });
}

export function useMyListings() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["ex-mine"], queryFn: () => apiGet<{ listings: Listing[] }>("/exchange/me/listings"), retry: false });
  const accept = (result: { listings: Listing[] }) => {
    client.setQueryData(["ex-mine"], result);
    void client.invalidateQueries({ queryKey: ["ex-listings"] });
    void client.invalidateQueries({ queryKey: ["ex-meta"] });
  };
  const create = useMutation({ mutationFn: (form: ListingForm) => apiPost<{ listings: Listing[] }>("/exchange/listings", form), onSuccess: accept });
  const edit = useMutation({ mutationFn: ({ id, form }: { id: string; form: ListingForm }) => apiPut<{ listings: Listing[] }>(`/exchange/listings/${id}`, form), onSuccess: accept });
  const pause = useMutation({ mutationFn: ({ id, paused }: { id: string; paused: boolean }) => apiPatch<{ listings: Listing[] }>(`/exchange/listings/${id}`, { paused }), onSuccess: accept });
  const remove = useMutation({ mutationFn: (id: string) => apiDelete<{ listings: Listing[] }>(`/exchange/listings/${id}`), onSuccess: accept });
  return { listings: query.data?.listings ?? [], loading: query.isPending, create, edit, pause, remove };
}

export function useProfile() {
  const client = useQueryClient();
  return useMutation({ mutationFn: (name: string) => apiPut<{ display_name: string }>("/exchange/me/profile", { name }), onSuccess: () => void client.invalidateQueries({ queryKey: ["ex-meta"] }) });
}

export function useThreads() {
  return useQuery({ queryKey: ["ex-threads"], queryFn: () => apiGet<{ threads: Thread[] }>("/exchange/threads"), refetchInterval: 20_000, retry: false });
}

export function useThread(id: string | null) {
  return useQuery({ queryKey: ["ex-thread", id], queryFn: () => apiGet<{ thread: Thread }>(`/exchange/threads/${id}`), enabled: !!id, refetchInterval: 10_000, retry: false });
}

export function useSendMessage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, message }: { id: string; message: string }) => apiPost<{ thread: Thread }>(`/exchange/threads/${id}/messages`, { message }),
    onSuccess: (result) => {
      client.setQueryData(["ex-thread", result.thread.id], result);
      void client.invalidateQueries({ queryKey: ["ex-threads"] });
    },
  });
}

export function useEnquire() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, message }: { id: string; message: string }) => apiPost<{ thread: Thread }>(`/exchange/listings/${id}/enquire`, { message }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["ex-threads"] }),
  });
}

export function useReport() {
  return useMutation({ mutationFn: ({ id, reason }: { id: string; reason: string }) => apiPost<{ message: string }>(`/exchange/listings/${id}/report`, { reason }) });
}

export function useQueue(enabled: boolean) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["ex-queue"], queryFn: () => apiGet<Queue>("/exchange/admin/queue"), enabled, retry: false });
  const decide = useMutation({
    mutationFn: ({ id, action, note }: { id: string; action: "approve" | "reject" | "remove"; note?: string }) => apiPost<Queue>(`/exchange/admin/listings/${id}`, { action, note: note ?? "" }),
    onSuccess: (result) => {
      client.setQueryData(["ex-queue"], result);
      void client.invalidateQueries({ queryKey: ["ex-meta"] });
      void client.invalidateQueries({ queryKey: ["ex-listings"] });
    },
  });
  return { queue: query.data, loading: query.isPending && enabled, decide };
}
