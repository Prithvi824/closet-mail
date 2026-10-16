import { InboxIcon } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useActivity } from "@/features/activity/api";
import { DailyChart } from "@/features/activity/DailyChart";
import { RecentMailTable } from "@/features/activity/RecentMailTable";
import { errorMessage } from "@/lib/http";

const WINDOWS = [7, 30, 90];

interface StatProps {
  label: string;
  value: number;
}

function Stat({ label, value }: StatProps) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

export function ActivityPage() {
  const [days, setDays] = useState(30);
  const activity = useActivity(days);
  const daily = activity.data?.daily ?? [];
  const forwards = daily.reduce((sum, day) => sum + day.forwards, 0);
  const replies = daily.reduce((sum, day) => sum + day.replies, 0);

  return (
    <>
      <PageHeader
        title="Activity"
        description="What happened to your mail. Senders and subjects are never stored here."
        actions={
          <Select value={String(days)} onValueChange={(value) => setDays(Number(value))}>
            <SelectTrigger aria-label="Time window" className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map((window) => (
                <SelectItem key={window} value={String(window)}>
                  Last {window} days
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      {activity.isPending ? <Skeleton className="h-64 w-full" /> : null}
      {activity.isError ? (
        <p className="text-sm text-destructive">{errorMessage(activity.error, "Could not load activity")}</p>
      ) : null}
      {activity.data ? (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Forwarded" value={forwards} />
            <Stat label="Replies sent" value={replies} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Per day</CardTitle>
              <CardDescription>Delivered forwards and replies (UTC days).</CardDescription>
            </CardHeader>
            <CardContent>
              <DailyChart days={daily} />
            </CardContent>
          </Card>
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">Recent mail</h2>
            {activity.data.recent.length === 0 ? (
              <EmptyState icon={InboxIcon} title="No mail yet">
                Messages to your aliases appear here once they are processed.
              </EmptyState>
            ) : (
              <RecentMailTable rows={activity.data.recent} />
            )}
          </section>
        </div>
      ) : null}
    </>
  );
}
