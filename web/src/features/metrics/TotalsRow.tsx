import type { OutcomeTotals } from "@/lib/api";

interface StatProps {
  label: string;
  value: number | string;
}

/** One big number with its label. */
export function Stat({ label, value }: StatProps) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

interface TotalsRowProps {
  totals: OutcomeTotals;
}

/** Received mail by outcome, plus replies sent. */
export function TotalsRow({ totals }: TotalsRowProps) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="Received" value={totals.received} />
      <Stat label="Delivered" value={totals.delivered} />
      <Stat label="Quarantined" value={totals.quarantined} />
      <Stat label="Blocked" value={totals.blocked} />
      <Stat label="Dropped" value={totals.discarded} />
      <Stat label="Replies sent" value={totals.replies} />
    </div>
  );
}
