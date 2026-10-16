import { ShieldCheckIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDeleteQuarantined, useQuarantine, useReleaseQuarantined } from "@/features/quarantine/api";
import type { QuarantineItem } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

export function QuarantinePage() {
  const [released, setReleased] = useState<string[]>([]);
  const [deleting, setDeleting] = useState<QuarantineItem | null>(null);
  const items = useQuarantine();
  const release = useReleaseQuarantined();
  const remove = useDeleteQuarantined();

  async function releaseItem(item: QuarantineItem) {
    await release.mutateAsync(item.id).then(
      () => {
        setReleased((ids) => [...ids, item.id]);
        toast.success("Release queued; the message will arrive shortly");
      },
      (error: unknown) => toast.error(errorMessage(error)),
    );
  }

  async function confirmDelete() {
    if (!deleting) return;
    await remove.mutateAsync(deleting.id).then(
      () => toast.success("Message deleted"),
      (error: unknown) => toast.error(errorMessage(error)),
    );
    setDeleting(null);
  }

  return (
    <>
      <PageHeader
        title="Quarantine"
        description="Suspected spam held for 7 days. Release what you want delivered; the rest is deleted automatically."
      />
      {items.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {items.isError ? (
        <p className="text-sm text-destructive">{errorMessage(items.error, "Could not load quarantine")}</p>
      ) : null}
      {items.data && items.data.length === 0 ? (
        <EmptyState icon={ShieldCheckIcon} title="Nothing in quarantine">
          Messages scored as likely spam show up here instead of your inbox.
        </EmptyState>
      ) : null}
      {items.data && items.data.length > 0 ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Message</TableHead>
                <TableHead className="hidden md:table-cell">Alias</TableHead>
                <TableHead className="w-px text-right">Score</TableHead>
                <TableHead className="hidden w-px lg:table-cell">Expires</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.data.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="w-full max-w-0">
                    <p className="truncate font-medium">{item.subject || "(no subject)"}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {item.sender} · {formatDateTime(item.created_at)}
                    </p>
                  </TableCell>
                  <TableCell className="hidden font-mono text-xs md:table-cell">{item.alias_address ?? "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{item.spam_score.toFixed(1)}</TableCell>
                  <TableCell className="hidden whitespace-nowrap text-muted-foreground lg:table-cell">
                    {formatRelative(item.expires_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {released.includes(item.id) ? (
                        <Badge variant="secondary">Releasing</Badge>
                      ) : (
                        <Button size="sm" variant="outline" disabled={release.isPending} onClick={() => void releaseItem(item)}>
                          Release
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => setDeleting(item)}>
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this message?"
        description="It is removed for good and will not be delivered."
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
