import { useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDelete, apiGet, apiPatch, apiPut } from "@/lib/api";
import type { AnnouncementsResponse, Layout, StockNews, StocksMeta, Watchlists } from "@/lib/premium";

// Server-side, per-user data for the premium pages. Everything here is read and written through /api/premium/me/*,
// which only returns the signed-in user's own watchlists and chart layouts.

export const FAVOURITES = "Favourites";

export { keepPreviousData };

export function useStocksMeta() {
  return useQuery({ queryKey: ["premium-stocks-meta"], queryFn: () => apiGet<StocksMeta>("/premium/stocks-meta"), staleTime: 3_600_000, retry: false });
}

export function useStockNews(symbol: string) {
  return useQuery({ queryKey: ["premium-stock-news", symbol], queryFn: () => apiGet<StockNews>(`/premium/stock/${encodeURIComponent(symbol)}/news`), staleTime: 300_000, retry: false });
}

export function useStockAnnouncements(symbol: string) {
  return useQuery({ queryKey: ["premium-stock-announcements", symbol], queryFn: () => apiGet<AnnouncementsResponse>(`/premium/stock/${encodeURIComponent(symbol)}/announcements`), staleTime: 600_000, retry: false });
}

interface ListsPayload {
  watchlists: Watchlists;
  max_lists?: number;
}

const LISTS_KEY = ["premium-watchlists"];

export function useWatchlists() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: LISTS_KEY, queryFn: () => apiGet<ListsPayload>("/premium/me/watchlists"), retry: false });
  // What the screen shows while a change is still on its way to the server. React state, not the query cache: the cache notifies
  // asynchronously, which would let a controlled checkbox flicker back for a moment after a click.
  const [overlay, setOverlay] = useState<Watchlists | null>(null);
  const inflight = useRef(0);
  const lists = overlay ?? query.data?.watchlists ?? {};
  const show = (next: Watchlists) => client.setQueryData<ListsPayload>(LISTS_KEY, (old) => ({ ...(old ?? {}), watchlists: next }));

  // Changes are sent as "add these, remove those" and applied to the list as it is on the server, so a stale screen can never wipe a list.
  const change = useMutation({
    mutationFn: ({ name, add, remove }: { name: string; add: string[]; remove: string[] }) => apiPatch<ListsPayload>(`/premium/me/watchlists/${encodeURIComponent(name)}`, { add, remove }),
    onSuccess: (result) => show(result.watchlists),
    onError: () => void client.invalidateQueries({ queryKey: LISTS_KEY }), // put the server's truth back on the screen
  });
  const remove = useMutation({
    mutationFn: (name: string) => apiDelete<ListsPayload>(`/premium/me/watchlists/${encodeURIComponent(name)}`),
    onSuccess: (result) => show(result.watchlists),
  });

  return {
    lists,
    ready: !query.isPending && !query.isError, // never edit before the real lists are known
    loading: query.isPending,
    failed: query.isError,
    maxLists: query.data?.max_lists ?? 10,
    saving: change.isPending || remove.isPending,
    error: change.error ?? remove.error,
    has: (name: string, symbol: string) => (lists[name] ?? []).includes(symbol),
    toggle: (name: string, symbol: string) => {
      const current = lists[name] ?? [];
      const adding = !current.includes(symbol);
      inflight.current += 1;
      setOverlay({ ...lists, [name]: adding ? [...current, symbol] : current.filter((s) => s !== symbol) });
      change.mutate(
        { name, add: adding ? [symbol] : [], remove: adding ? [] : [symbol] },
        {
          onSettled: () => {
            inflight.current -= 1;
            if (inflight.current === 0) setOverlay(null);
          },
        },
      );
    },
    create: (name: string, symbols: string[] = []) => change.mutateAsync({ name, add: symbols, remove: [] }),
    remove: (name: string) => remove.mutateAsync(name),
  };
}

interface LayoutsPayload {
  layouts: Record<string, Layout>;
  max_layouts?: number;
}

const LAYOUTS_KEY = ["premium-layouts"];

export function useLayouts() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: LAYOUTS_KEY, queryFn: () => apiGet<LayoutsPayload>("/premium/me/layouts"), retry: false });
  const save = useMutation({
    mutationFn: ({ name, layout }: { name: string; layout: Layout }) => apiPut<LayoutsPayload>(`/premium/me/layouts/${encodeURIComponent(name)}`, layout),
    onSuccess: (result) => client.setQueryData<LayoutsPayload>(LAYOUTS_KEY, (old) => ({ ...(old ?? {}), layouts: result.layouts })),
  });
  const remove = useMutation({
    mutationFn: (name: string) => apiDelete<LayoutsPayload>(`/premium/me/layouts/${encodeURIComponent(name)}`),
    onSuccess: (result) => client.setQueryData<LayoutsPayload>(LAYOUTS_KEY, (old) => ({ ...(old ?? {}), layouts: result.layouts })),
  });
  return {
    layouts: query.data?.layouts ?? {},
    loading: query.isPending,
    failed: query.isError,
    busy: save.isPending || remove.isPending,
    error: save.error ?? remove.error,
    save: (name: string, layout: Layout) => save.mutateAsync({ name, layout }),
    remove: (name: string) => remove.mutateAsync(name),
  };
}

// A string kept in sessionStorage so list filters survive a trip to a stock page and back. Storage can be blocked: it then behaves like useState.
export function useSessionState<T extends string>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (window.sessionStorage.getItem(key) as T | null) ?? initial;
    } catch {
      return initial;
    }
  });
  const set = (next: T) => {
    setValue(next);
    try {
      window.sessionStorage.setItem(key, next);
    } catch {
      // private mode or blocked storage: the value just isn't remembered
    }
  };
  return [value, set];
}
