import { KeyRoundIcon, MoreHorizontalIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { TableCell, TableRow } from "@/components/ui/table";
import type { Recipient } from "@/lib/api";

export type RecipientAction = "pgp" | "resend" | "disable" | "enable" | "delete";

interface RecipientRowProps {
  recipient: Recipient;
  onAction: (action: RecipientAction, recipient: Recipient) => void;
  onDefaultChange: (recipient: Recipient, value: boolean) => void;
  defaultPending: boolean;
}

function StatusBadges({ recipient }: { recipient: Recipient }) {
  return (
    <div className="flex flex-wrap gap-1">
      {!recipient.verified ? <Badge variant="secondary">Unverified</Badge> : null}
      {recipient.disabled ? <Badge variant="destructive">Disabled</Badge> : null}
      {recipient.pgp_fingerprint ? (
        <Badge variant="outline">
          <KeyRoundIcon /> PGP
        </Badge>
      ) : null}
    </div>
  );
}

/** One inbox with its default switch, status and an actions menu. */
export function RecipientRow({ recipient, onAction, onDefaultChange, defaultPending }: RecipientRowProps) {
  return (
    <TableRow>
      <TableCell className="w-full max-w-0">
        <p className="truncate font-medium">{recipient.email}</p>
        {recipient.pgp_fingerprint ? (
          <p className="truncate font-mono text-xs text-muted-foreground">{recipient.pgp_fingerprint}</p>
        ) : null}
      </TableCell>
      <TableCell className="w-px">
        <Switch
          aria-label={`Default inbox: ${recipient.email}`}
          checked={recipient.forward_by_default}
          disabled={defaultPending}
          onCheckedChange={(value) => onDefaultChange(recipient, value)}
        />
      </TableCell>
      <TableCell>
        <StatusBadges recipient={recipient} />
      </TableCell>
      <TableCell className="w-px">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${recipient.email}`}>
              <MoreHorizontalIcon />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => onAction("pgp", recipient)}>
              {recipient.pgp_fingerprint ? "Change PGP key" : "Add PGP key"}
            </DropdownMenuItem>
            {!recipient.verified ? (
              <DropdownMenuItem onSelect={() => onAction("resend", recipient)}>
                Resend verification
              </DropdownMenuItem>
            ) : null}
            {recipient.verified ? (
              <DropdownMenuItem onSelect={() => onAction(recipient.disabled ? "enable" : "disable", recipient)}>
                {recipient.disabled ? "Enable forwarding" : "Pause forwarding"}
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={() => onAction("delete", recipient)}>
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}
