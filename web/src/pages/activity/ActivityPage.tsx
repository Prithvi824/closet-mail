import { ChevronLeftIcon, ChevronRightIcon, InboxIcon } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useActivity } from "@/features/activity/api";
import { DailyChart } from "@/features/activity/DailyChart";
import { RecentMailTable } from "@/features/activity/RecentMailTable";
import { CountList } from "@/features/metrics/CountList";
import { TotalsRow } from "@/features/metrics/TotalsRow";
import { WindowSelect } from "@/features/metrics/WindowSelect";
import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import { errorMessage } from "@/lib/http";

/** One subdomain's mail: how much, from whom, to which aliases and inboxes. */
export function ActivityPage() {
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(1);
  const label = useSubdomainLabel();
  const activity = useActivity(days, page);

  function changeDays(next: number) {
    setDays(next);
    setPage(1);
  }

  return (
    <>
      <PageHeader
        title="Activity"
        description={`Mail to ${label}.closetcompute.online, by the time it arrived (UTC).`}
        actions={<WindowSelect days={days} onChange={changeDays} />}
      />
      {activity.isPending ? <Skeleton className="h-64 w-full" /> : null}
      {activity.isError ? (
        <p className="text-sm text-destructive">{errorMessage(activity.error, "Could not load activity")}</p>
      ) : null}
      {activity.data ? (
        <div className="flex flex-col gap-6">
          <TotalsRow totals={activity.data.totals} />
          <Card>
            <CardHeader>
              <CardTitle>Per day</CardTitle>
              <CardDescription>Received mail, how much was delivered, and replies sent.</CardDescription>
            </CardHeader>
            <CardContent>
              <DailyChart days={activity.data.daily} />
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <CountList title="Sender domains" items={activity.data.top_sender_domains} />
            <CountList title="Senders" items={activity.data.top_senders} />
            <CountList title="Aliases" items={activity.data.per_alias} />
            <CountList title="Inboxes" items={activity.data.per_inbox} empty="No deliveries yet" />
          </div>
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">Recent mail</h2>
            {activity.data.recent.length === 0 ? (
              <EmptyState icon={InboxIcon} title="No mail yet">
                Messages to this subdomain appear here once they are processed.
              </EmptyState>
            ) : (
              <RecentMailTable rows={activity.data.recent} />
            )}
            <div className="flex items-center justify-end gap-1 text-sm text-muted-foreground">
              <span className="mr-2">Page {page}</span>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Previous page"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                <ChevronLeftIcon />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Next page"
                disabled={!activity.data.has_more}
                onClick={() => setPage(page + 1)}
              >
                <ChevronRightIcon />
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
