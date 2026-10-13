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
  useSetRecipientDisabled,
} from "@/features/recipients/api";
import { PgpKeyDialog } from "@/features/recipients/PgpKeyDialog";
import { RecipientRow, type RecipientAction } from "@/features/recipients/RecipientRow";
import { useUpdateSettings } from "@/features/settings/api";
import type { Recipient } from "@/lib/api";
import { errorMessage } from "@/lib/http";

export function RecipientsPage() {
  const [pgpFor, setPgpFor] = useState<Recipient | null>(null);
  const [deleting, setDeleting] = useState<Recipient | null>(null);
  const recipients = useRecipients();
  const setDisabled = useSetRecipientDisabled();
  const resend = useResendVerification();
  const remove = useDeleteRecipient();
  const settings = useUpdateSettings();

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
      default: () =>
        void run(settings.mutateAsync({ default_recipient_id: id }), `${recipient.email} is now the default`),
      resend: () => void run(resend.mutateAsync(id), "Verification link sent"),
      disable: () => void run(setDisabled.mutateAsync({ id, disabled: true }), "Forwarding paused"),
      enable: () => void run(setDisabled.mutateAsync({ id, disabled: false }), "Forwarding enabled"),
    };
    handlers[action]();
  }

  async function confirmDelete() {
    if (!deleting) return;
    await run(remove.mutateAsync(deleting.id), "Recipient deleted");
    setDeleting(null);
  }

  return (
    <>
      <PageHeader
        title="Recipients"
        description="Your real inboxes. Aliases forward here, and only these addresses can reply through an alias."
      />
      <AddRecipientForm />
      {recipients.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {recipients.data ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Address</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recipients.data.map((recipient) => (
                <RecipientRow key={recipient.id} recipient={recipient} onAction={onAction} />
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      <PgpKeyDialog key={pgpFor?.id ?? "none"} recipient={pgpFor} onClose={() => setPgpFor(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this recipient?"
        description={`Aliases forwarding to ${deleting?.email ?? ""} fall back to your default recipient.`}
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
