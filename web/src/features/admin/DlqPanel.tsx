import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDlq, useRetryDlq } from "@/features/admin/api";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/http";

/** Dead-lettered jobs: inspect on demand, move one or all back to the inbound queue. */
export function DlqPanel() {
  const [inspecting, setInspecting] = useState(false);
  const dlq = useDlq(inspecting);
  const retry = useRetryDlq();

  async function move(r2Keys: string[] | null) {
    const result = await retry.mutateAsync(r2Keys).catch((error: unknown) => {
      toast.error(errorMessage(error));
      return null;
    });
    if (!result) return;
    toast.success(`${result.moved} job${result.moved === 1 ? "" : "s"} sent back for processing`);
    setInspecting(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Dead-letter queue</CardTitle>
        <CardDescription>
          Jobs that failed 5 times. Cloudflare keeps them for one day; fix the cause, then retry.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!inspecting ? (
          <Button variant="outline" className="self-start" onClick={() => setInspecting(true)}>
            Inspect dead letters
          </Button>
        ) : null}
        {inspecting && dlq.isPending ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
        {dlq.isError ? <p className="text-sm text-destructive">{errorMessage(dlq.error)}</p> : null}
        {inspecting && dlq.data && dlq.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">The dead-letter queue is empty.</p>
        ) : null}
        {inspecting && dlq.data && dlq.data.length > 0 ? (
          <>
            <div className="overflow-hidden rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Recipient</TableHead>
                    <TableHead className="w-px">Received</TableHead>
                    <TableHead className="w-px text-right">Tries</TableHead>
                    <TableHead className="w-px">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dlq.data.map((item) => (
                    <TableRow key={item.lease_id}>
                      <TableCell className="max-w-0 truncate font-mono text-xs">{item.rcpt_to}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(item.received_at)}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.attempts}</TableCell>
                      <TableCell>
                        <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => void move([item.r2_key])}>
                          Retry
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <Button className="self-start" disabled={retry.isPending} onClick={() => void move(null)}>
              Retry all
            </Button>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
