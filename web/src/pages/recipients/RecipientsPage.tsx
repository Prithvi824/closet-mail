import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AddRecipientForm } from "@/features/recipients/AddRecipientForm";
import {
  useDeleteRecipient,
  useRecipients,
  useResendVerification,
  useSetRecipientDefault,
  useSetRecipientDisabled,
} from "@/features/recipients/api";
import { PgpKeyDialog } from "@/features/recipients/PgpKeyDialog";
import { RecipientRow, type RecipientAction } from "@/features/recipients/RecipientRow";
import type { Recipient } from "@/lib/api";
import { errorMessage } from "@/lib/http";

export function RecipientsPage() {
  const [pgpFor, setPgpFor] = useState<Recipient | null>(null);
  const [deleting, setDeleting] = useState<Recipient | null>(null);
  const recipients = useRecipients();
  const setDisabled = useSetRecipientDisabled();
  const resend = useResendVerification();
  const remove = useDeleteRecipient();
  const setDefault = useSetRecipientDefault();

  async function run(promise: Promise<unknown>, success: string) {
    await promise.then(
      () => toast.success(success),
      (error: unknown) => toast.error(errorMessage(error)),
    );
  }

  function onAction(action: RecipientAction, recipient: Recipient) {
    const id = recipient.id;
    const handlers: Record<RecipientAction, () => void> = {
      pgp: () => setPgpFor(recipient),
      delete: () => setDeleting(recipient),
      resend: () => void run(resend.mutateAsync(id), "Verification link sent"),
      disable: () => void run(setDisabled.mutateAsync({ id, disabled: true }), "Forwarding paused"),
      enable: () => void run(setDisabled.mutateAsync({ id, disabled: false }), "Forwarding enabled"),
    };
    handlers[action]();
  }

  function onDefaultChange(recipient: Recipient, value: boolean) {
    const message = value ? `${recipient.email} is now a default inbox` : `${recipient.email} is no longer a default inbox`;
    void run(setDefault.mutateAsync({ id: recipient.id, forward_by_default: value }), message);
  }

  async function confirmDelete() {
    if (!deleting) return;
    await run(remove.mutateAsync(deleting.id), "Inbox deleted");
    setDeleting(null);
  }

  return (
    <>
      <PageHeader
        title="Inboxes"
        description="Real inboxes. Aliases forward here, and only these addresses can reply through an alias. Aliases with no inbox ticked go to every default inbox."
      />
      <AddRecipientForm />
      {recipients.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {recipients.isError ? (
        <p className="text-sm text-destructive">{errorMessage(recipients.error, "Could not load inboxes")}</p>
      ) : null}
      {recipients.data ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Address</TableHead>
                <TableHead className="w-px">Default</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recipients.data.map((recipient) => (
                <RecipientRow
                  key={recipient.id}
                  recipient={recipient}
                  onAction={onAction}
                  onDefaultChange={onDefaultChange}
                  defaultPending={setDefault.isPending}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      <PgpKeyDialog key={pgpFor?.id ?? "none"} recipient={pgpFor} onClose={() => setPgpFor(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this inbox?"
        description={`Aliases forwarding only to ${deleting?.email ?? ""} fall back to the default inboxes.`}
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
