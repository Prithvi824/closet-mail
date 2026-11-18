import { useState } from "react";
import { Link } from "react-router";

import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DailyChart } from "@/features/activity/DailyChart";
import { useOverview } from "@/features/metrics/api";
import { CountList } from "@/features/metrics/CountList";
import { Stat, TotalsRow } from "@/features/metrics/TotalsRow";
import { WindowSelect } from "@/features/metrics/WindowSelect";
import type { Overview } from "@/lib/api";
import { errorMessage } from "@/lib/http";
import { subdomainPage } from "@/lib/paths";

interface PerSubdomainTableProps {
  rows: Overview["per_subdomain"];
}

/** Each subdomain's totals over the window, linking to its activity. */
function PerSubdomainTable({ rows }: PerSubdomainTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table aria-label="Mail per subdomain">
        <TableHeader>
          <TableRow>
            <TableHead>Subdomain</TableHead>
            <TableHead className="text-right">Received</TableHead>
            <TableHead className="text-right">Delivered</TableHead>
            <TableHead className="text-right">Quarantined</TableHead>
            <TableHead className="text-right">Dropped</TableHead>
            <TableHead className="text-right">Replies</TableHead>
            <TableHead className="text-right">Sends today</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label}>
              <TableCell>
                <Link to={subdomainPage(row.label, "activity")} className="font-medium underline-offset-4 hover:underline">
                  {row.label}
                </Link>
                {row.display_name ? <p className="text-xs text-muted-foreground">{row.display_name}</p> : null}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.totals.received}</TableCell>
              <TableCell className="text-right tabular-nums">{row.totals.delivered}</TableCell>
              <TableCell className="text-right tabular-nums">{row.totals.quarantined}</TableCell>
              <TableCell className="text-right tabular-nums">{row.totals.discarded + row.totals.blocked}</TableCell>
              <TableCell className="text-right tabular-nums">{row.totals.replies}</TableCell>
              <TableCell className="text-right tabular-nums">
                {row.sends_today} / {row.send_share}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Mail across every subdomain the operator runs. */
export function OverviewPage() {
  const [days, setDays] = useState(30);
  const overview = useOverview(days);

  return (
    <>
      <PageHeader
        title="Overview"
        description="Mail across every subdomain, by the time it arrived (UTC)."
        actions={<WindowSelect days={days} onChange={setDays} />}
      />
      {overview.isPending ? <Skeleton className="h-64 w-full" /> : null}
      {overview.isError ? (
        <p className="text-sm text-destructive">{errorMessage(overview.error, "Could not load the overview")}</p>
      ) : null}
      {overview.data ? (
        <div className="flex flex-col gap-6">
          <TotalsRow totals={overview.data.totals} />
          <Card>
            <CardHeader>
              <CardTitle>Per day</CardTitle>
              <CardDescription>Received mail, how much was delivered, and replies sent.</CardDescription>
            </CardHeader>
            <CardContent>
              <DailyChart days={overview.data.daily} />
            </CardContent>
          </Card>
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">Subdomains</h2>
            <PerSubdomainTable rows={overview.data.per_subdomain} />
          </section>
          <div className="grid gap-4 md:grid-cols-2">
            <CountList title="Top sender domains" items={overview.data.top_sender_domains} />
            <Stat label="Sends today against the daily cap" value={`${overview.data.sends_today} / ${overview.data.send_cap}`} />
          </div>
        </div>
      ) : null}
    </>
  );
}
