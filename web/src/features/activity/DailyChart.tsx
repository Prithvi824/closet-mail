import type { DailyActivity } from "@/lib/api";

interface DailyChartProps {
  days: DailyActivity[];
}

const dayLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** Stacked bars per day: forwards (primary) and replies (muted). Pure CSS, no chart library. */
export function DailyChart({ days }: DailyChartProps) {
  const peak = Math.max(1, ...days.map((day) => day.forwards + day.replies));

  return (
    <figure className="flex flex-col gap-2">
      <div className="flex h-40 items-end gap-0.5" role="img" aria-label="Forwards and replies per day">
        {days.map((day) => {
          const total = day.forwards + day.replies;
          const label = `${dayLabel.format(new Date(day.day))}: ${day.forwards} forwarded, ${day.replies} replies`;
          return (
            <div key={day.day} className="group flex h-full flex-1 flex-col justify-end" title={label}>
              <div
                className="w-full rounded-t-sm bg-muted-foreground/40"
                style={{ height: `${(day.replies / peak) * 100}%` }}
              />
              <div
                className="w-full bg-primary group-hover:opacity-80"
                style={{ height: `${(day.forwards / peak) * 100}%`, minHeight: total ? 2 : 0 }}
              />
            </div>
          );
        })}
      </div>
      <figcaption className="flex justify-between text-xs text-muted-foreground">
        <span>{days.length ? dayLabel.format(new Date(days[0].day)) : ""}</span>
        <span className="flex gap-3">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-primary" /> Forwarded
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-sm bg-muted-foreground/40" /> Replies
          </span>
        </span>
        <span>Today</span>
      </figcaption>
    </figure>
  );
}
