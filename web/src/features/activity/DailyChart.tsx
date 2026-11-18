import type { DailyPoint } from "@/lib/api";

interface DailyChartProps {
  days: DailyPoint[];
}

const dayLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** Stacked bars per day: delivered, received but not delivered, and replies. Pure CSS. */
export function DailyChart({ days }: DailyChartProps) {
  const peak = Math.max(1, ...days.map((day) => Math.max(day.received, day.delivered) + day.replies));

  return (
    <figure className="flex flex-col gap-2">
      <div className="flex h-40 items-end gap-0.5" role="img" aria-label="Mail received, delivered and replies per day">
        {days.map((day) => {
          const held = Math.max(0, day.received - day.delivered);
          const label = `${dayLabel.format(new Date(day.day))}: ${day.received} received, ${day.delivered} delivered, ${day.replies} replies`;
          return (
            <div key={day.day} className="group flex h-full flex-1 flex-col justify-end" title={label}>
              <div
                className="w-full rounded-t-sm bg-muted-foreground/60"
                style={{ height: `${(day.replies / peak) * 100}%` }}
              />
              <div className="w-full bg-muted-foreground/25" style={{ height: `${(held / peak) * 100}%` }} />
              <div
                className="w-full bg-primary group-hover:opacity-80"
                style={{ height: `${(day.delivered / peak) * 100}%`, minHeight: day.delivered ? 2 : 0 }}
              />
            </div>
          );
        })}
      </div>
      <figcaption className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
        <span>{days.length ? dayLabel.format(new Date(days[0].day)) : ""}</span>
        <span className="flex flex-wrap gap-3">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-primary" /> Delivered
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-muted-foreground/25" /> Held or dropped
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-muted-foreground/60" /> Replies
          </span>
        </span>
        <span>Today</span>
      </figcaption>
    </figure>
  );
}
