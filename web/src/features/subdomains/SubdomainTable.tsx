import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/features/subdomains/StatusBadge";
import type { Subdomain } from "@/lib/api";

interface SubdomainTableProps {
  subdomains: Subdomain[];
  onManage: (label: string) => void;
}

/** One row per subdomain: status, inboxes, aliases and today's mail against its send share. */
export function SubdomainTable({ subdomains, onManage }: SubdomainTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Subdomain</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Default inboxes</TableHead>
            <TableHead className="text-right">Aliases</TableHead>
            <TableHead className="text-right">Received today</TableHead>
            <TableHead className="text-right">Sends today</TableHead>
            <TableHead className="w-px">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {subdomains.map((item) => (
            <TableRow key={item.id}>
              <TableCell>
                <p className="font-medium">
                  {item.label}
                  {item.is_operator ? <span className="ml-2 text-xs text-muted-foreground">(you)</span> : null}
                </p>
                <p className="text-xs text-muted-foreground">{item.display_name ?? item.domain}</p>
              </TableCell>
              <TableCell>
                <StatusBadge state={item.status.state} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{item.default_inbox_count}</TableCell>
              <TableCell className="text-right tabular-nums">{item.alias_count}</TableCell>
              <TableCell className="text-right tabular-nums">{item.received_today}</TableCell>
              <TableCell className="text-right tabular-nums">
                {item.sends_today} / {item.send_share}
              </TableCell>
              <TableCell>
                <Button variant="outline" size="sm" aria-label={`Manage ${item.label}`} onClick={() => onManage(item.label)}>
                  Manage
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
