import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { MailOutcome, RecentMail } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const OUTCOME_LABELS: Record<MailOutcome, string> = {
  delivered: "Delivered",
  discarded: "Dropped",
  quarantined: "Quarantined",
  blocked: "Blocked",
  rejected_reply: "Reply refused",
  bounce_recorded: "Bounce",
};

const OUTCOME_VARIANTS: Record<MailOutcome, "default" | "secondary" | "destructive" | "outline"> = {
  delivered: "default",
  discarded: "secondary",
  quarantined: "outline",
  blocked: "secondary",
  rejected_reply: "destructive",
  bounce_recorded: "destructive",
};

/** Reason codes from the processor, in words. */
const REASON_LABELS: Record<string, string> = {
  spam: "spam score",
  dmarc_reject: "failed sender authentication",
  dmarc_fail: "failed sender authentication",
  blocklist: "on your blocklist",
  contact_blocked: "sender blocked",
  alias_inactive: "alias inactive",
  alias_deleted: "alias deleted",
  quota: "limit reached",
  unauthorized_sender: "not from your recipient",
  reply_disabled: "replies off",
  send_failed: "relay refused",
  loop: "mail loop",
};

interface RecentMailTableProps {
  rows: RecentMail[];
}

export function RecentMailTable({ rows }: RecentMailTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-px">When</TableHead>
            <TableHead className="w-px">Type</TableHead>
            <TableHead>Alias</TableHead>
            <TableHead className="w-px">Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(row.created_at)}</TableCell>
              <TableCell className="capitalize">{row.kind}</TableCell>
              <TableCell className="max-w-0 truncate font-mono text-xs">{row.alias_address ?? "—"}</TableCell>
              <TableCell className="whitespace-nowrap">
                <Badge variant={OUTCOME_VARIANTS[row.outcome]}>{OUTCOME_LABELS[row.outcome]}</Badge>
                {row.reason && row.reason in REASON_LABELS ? (
                  <span className="ml-2 text-xs text-muted-foreground">{REASON_LABELS[row.reason]}</span>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
