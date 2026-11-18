import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DeliveryStatus, MailEvent, MailOutcome } from "@/lib/api";
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

const DELIVERY_VARIANTS: Record<DeliveryStatus, "default" | "secondary" | "destructive" | "outline"> = {
  sent: "outline",
  delivered: "secondary",
  delayed: "outline",
  bounced: "destructive",
  complained: "destructive",
};

/** Reason codes from the processor, in words. */
const REASON_LABELS: Record<string, string> = {
  spam: "spam score",
  dmarc_reject: "failed sender authentication",
  dmarc_fail: "failed sender authentication",
  blocklist: "on the blocklist",
  contact_blocked: "sender blocked",
  alias_inactive: "alias inactive",
  alias_deleted: "alias deleted",
  quota: "limit reached",
  unauthorized_sender: "not from an inbox",
  reply_disabled: "replies off",
  send_failed: "relay refused",
  loop: "mail loop",
  unknown_alias: "unknown address",
  user_disabled: "subdomain suspended",
  no_sender: "no sender",
  no_recipient: "no inbox",
  redelivered: "already sent",
  unknown_token: "unknown reply address",
  unparsable_dsn: "unreadable bounce",
  hard: "hard bounce",
  soft: "soft bounce",
  delayed: "delayed",
};

interface DestinationsProps {
  row: MailEvent;
}

/** Each inbox a message went to, with what the provider reported. */
function Destinations({ row }: DestinationsProps) {
  if (row.destinations.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <ul className="flex flex-col gap-1">
      {row.destinations.map((destination, index) => (
        <li key={`${destination.inbox ?? "reply"}-${index}`} className="flex items-center gap-2">
          <span className="truncate">{destination.inbox ?? "correspondent"}</span>
          <Badge variant={DELIVERY_VARIANTS[destination.status]}>{destination.status}</Badge>
        </li>
      ))}
    </ul>
  );
}

interface RecentMailTableProps {
  rows: MailEvent[];
}

/** Recent mail: when, from whom, to which alias, delivered to which inboxes, and the result. */
export function RecentMailTable({ rows }: RecentMailTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table aria-label="Recent mail">
        <TableHeader>
          <TableRow>
            <TableHead className="w-px">When</TableHead>
            <TableHead className="w-px">Type</TableHead>
            <TableHead>Sender</TableHead>
            <TableHead>Alias</TableHead>
            <TableHead>Delivered to</TableHead>
            <TableHead className="w-px">Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} className="align-top">
              <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(row.received_at)}</TableCell>
              <TableCell className="capitalize">{row.kind}</TableCell>
              <TableCell className="max-w-48 truncate">{row.sender ?? row.sender_domain ?? "—"}</TableCell>
              <TableCell className="max-w-48 truncate font-mono text-xs">{row.alias_address ?? "—"}</TableCell>
              <TableCell className="text-xs">
                <Destinations row={row} />
              </TableCell>
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
