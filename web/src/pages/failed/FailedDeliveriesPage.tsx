import { MailCheckIcon } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useFailedDeliveries } from "@/features/failed/api";
import type { FailureKind } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/http";

const KIND_LABELS: Record<FailureKind, string> = {
  hard: "Bounced",
  soft: "Temporary failure",
  complaint: "Marked as spam",
  delayed: "Delayed",
  suppressed: "Suppressed",
};

const KIND_VARIANTS: Record<FailureKind, "destructive" | "secondary" | "outline"> = {
  hard: "destructive",
  soft: "secondary",
  complaint: "destructive",
  delayed: "outline",
  suppressed: "secondary",
};

export function FailedDeliveriesPage() {
  const failures = useFailedDeliveries();

  return (
    <>
      <PageHeader
        title="Failed deliveries"
        description="Bounces and delivery problems from the last 90 days. Three bounces in a row pause a recipient."
      />
      {failures.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {failures.isError ? (
        <p className="text-sm text-destructive">{errorMessage(failures.error, "Could not load failed deliveries")}</p>
      ) : null}
      {failures.data && failures.data.length === 0 ? (
        <EmptyState icon={MailCheckIcon} title="No delivery problems" />
      ) : null}
      {failures.data && failures.data.length > 0 ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-px">When</TableHead>
                <TableHead className="w-px">Problem</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {failures.data.map((failure) => (
                <TableRow key={failure.id}>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(failure.created_at)}</TableCell>
                  <TableCell>
                    <Badge variant={KIND_VARIANTS[failure.kind]}>{KIND_LABELS[failure.kind]}</Badge>
                  </TableCell>
                  <TableCell className="w-full max-w-0">
                    <p className="truncate text-sm">
                      {failure.recipient_email ? `To ${failure.recipient_email}` : failure.alias_address ? "Reply" : "Other message"}
                      {failure.alias_address ? ` · via ${failure.alias_address}` : ""}
                    </p>
                    {failure.detail ? (
                      <p className="truncate text-xs text-muted-foreground" title={failure.detail}>
                        {failure.detail}
                      </p>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </>
  );
}
