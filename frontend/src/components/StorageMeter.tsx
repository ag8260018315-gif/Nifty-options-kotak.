import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/lib/api";

interface Storage {
  limit_mb: number;
  used_mb: number;
  percent: number;
  status: "OK" | "HIGH" | "FULL";
  databases: Record<string, number>;
}

const TONE = { OK: "bg-emerald-400", HIGH: "bg-amber-300", FULL: "bg-rose-400" } as const;
const NOTE = {
  OK: "Plenty of room.",
  HIGH: "Getting full. Old snapshots are being cleared automatically to make room.",
  FULL: "Full. New sign-in codes and other saves will fail until space is freed. Old snapshots are being cleared automatically.",
} as const;

// Owner only: how much of the free database plan is used, so a full cluster never comes as a surprise.
export default function StorageMeter() {
  const { data } = useQuery({ queryKey: ["storage"], queryFn: () => apiGet<Storage>("/access/admin/storage"), refetchInterval: 120_000, retry: false });
  if (!data) return null;
  const width = Math.min(100, Math.max(2, data.percent));
  return (
    <section aria-labelledby="storage-title" data-testid="storage-meter">
      <h3 id="storage-title" className="text-sm font-semibold text-white">Database space</h3>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#1a2336]" role="img" aria-label={`${data.used_mb} of ${data.limit_mb} megabytes used`}>
        <div className={`h-full ${TONE[data.status]}`} style={{ width: `${width}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-slate-400">{data.used_mb} MB of {data.limit_mb} MB used ({data.percent}%). {NOTE[data.status]}</p>
    </section>
  );
}
