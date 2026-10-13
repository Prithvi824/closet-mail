import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type TileStatus = "ok" | "warn" | "bad" | "unknown";

const STATUS_STYLES: Record<TileStatus, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  unknown: "bg-muted-foreground/40",
};

interface HealthTileProps {
  label: string;
  value: ReactNode;
  status: TileStatus;
  hint?: ReactNode;
}

/** One health metric with a coloured status dot. */
export function HealthTile({ label, value, status, hint }: HealthTileProps) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className={cn("size-2 rounded-full", STATUS_STYLES[status])} aria-label={status} role="img" />
        {label}
      </div>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
