import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CountItem } from "@/lib/api";

interface CountListProps {
  title: string;
  items: CountItem[];
  /** Shown when there is nothing to count. */
  empty?: string;
}

/** A ranked list (sender domains, senders, aliases, inboxes) with proportional bars. */
export function CountList({ title, items, empty = "Nothing yet" }: CountListProps) {
  const peak = Math.max(1, ...items.map((item) => item.count));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          <h3>{title}</h3>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {items.map((item) => (
              <li key={item.key} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="truncate">{item.key}</span>
                  <span className="tabular-nums text-muted-foreground">{item.count}</span>
                </div>
                <div className="h-1.5 rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${(item.count / peak) * 100}%` }} />
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
