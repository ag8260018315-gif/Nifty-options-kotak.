import { useEffect, useRef, useState, type ReactNode } from "react";

// Briefly tints a live number green or red when it ticks up or down.
export default function Flash({ value, children }: { value: number; children: ReactNode }) {
  const previous = useRef(value);
  const [dir, setDir] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    if (value === previous.current) return;
    setDir(value > previous.current ? "up" : "down");
    previous.current = value;
    const timer = window.setTimeout(() => setDir(null), 700);
    return () => window.clearTimeout(timer);
  }, [value]);
  return <span className={`rounded px-1 transition-colors duration-500 ${dir === "up" ? "bg-emerald-500/25" : dir === "down" ? "bg-rose-500/25" : ""}`}>{children}</span>;
}
