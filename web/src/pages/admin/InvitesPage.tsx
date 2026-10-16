import { SendIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCreateInvite, useInvites } from "@/features/admin/api";
import type { Invite } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

function inviteStatus(invite: Invite): { label: string; variant: "default" | "secondary" | "outline" } {
  if (invite.used_at) return { label: "Accepted", variant: "default" };
  if (new Date(invite.expires_at).getTime() < Date.now()) return { label: "Expired", variant: "outline" };
  return { label: "Pending", variant: "secondary" };
}

export function InvitesPage() {
  const [email, setEmail] = useState("");
  const invites = useInvites();
  const create = useCreateInvite();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const invite = await create.mutateAsync(email.trim()).catch(() => null);
    if (!invite) return;
    toast.success(`Invite sent to ${invite.email}`);
    setEmail("");
  }

  return (
    <>
      <PageHeader title="Invites" description="Accounts are invite-only. An invite link is valid for 7 days." />
      <form onSubmit={submit} className="mb-4 flex flex-col gap-2">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            type="email"
            aria-label="Email to invite"
            placeholder="friend@example.com"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              create.reset();
            }}
          />
          <Button type="submit" disabled={!email.trim() || create.isPending}>
            <SendIcon /> Send invite
          </Button>
        </div>
        <FormError message={create.error ? errorMessage(create.error) : null} />
      </form>
      {invites.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {invites.isError ? (
        <p className="text-sm text-destructive">{errorMessage(invites.error, "Could not load invites")}</p>
      ) : null}
      {invites.data && invites.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No invites sent yet.</p>
      ) : null}
      {invites.data && invites.data.length > 0 ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead className="w-px">Status</TableHead>
                <TableHead className="hidden w-px md:table-cell">Sent</TableHead>
                <TableHead className="hidden w-px md:table-cell">Expires</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.data.map((invite) => {
                const status = inviteStatus(invite);
                return (
                  <TableRow key={invite.id}>
                    <TableCell className="w-full max-w-0 truncate">{invite.email}</TableCell>
                    <TableCell>
                      <Badge variant={status.variant}>{status.label}</Badge>
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell">
                      {formatDateTime(invite.created_at)}
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell">
                      {invite.used_at ? "—" : formatRelative(invite.expires_at)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </>
  );
}
