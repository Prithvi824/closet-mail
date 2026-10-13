import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { CheckList } from "@/components/CheckList";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { CopyButton } from "@/components/CopyButton";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { AliasStateBadge } from "@/features/aliases/AliasStateBadge";
import {
  useAlias,
  useDeleteAlias,
  useForgetAlias,
  useRestoreAlias,
  useUpdateAlias,
} from "@/features/aliases/api";
import { ContactsList } from "@/features/aliases/ContactsList";
import { useLabels } from "@/features/labels/api";
import { useRecipients } from "@/features/recipients/api";
import type { Alias, AliasUpdate } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

interface AliasDetailSheetProps {
  aliasId: string | null;
  onClose: () => void;
}

interface SectionProps {
  title: string;
  children: ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  );
}

interface ToggleRowProps {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}

function ToggleRow({ id, label, hint, checked, disabled, onChange }: ToggleRowProps) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}

interface AliasDetailsProps {
  alias: Alias;
  onClose: () => void;
}

/** Editable settings of one loaded alias (remounted per alias so drafts reset). */
function AliasDetails({ alias, onClose }: AliasDetailsProps) {
  const [description, setDescription] = useState(alias.description ?? "");
  const [recipientIds, setRecipientIds] = useState(alias.recipient_ids);
  const [labelIds, setLabelIds] = useState(alias.label_ids);
  const [confirm, setConfirm] = useState<"delete" | "forget" | null>(null);
  const recipients = useRecipients();
  const labels = useLabels();
  const update = useUpdateAlias();
  const remove = useDeleteAlias();
  const restore = useRestoreAlias();
  const forget = useForgetAlias();
  const isDeleted = alias.state === "deleted";
  const isEditable = alias.state === "active" || alias.state === "inactive";
  const recipientOptions = (recipients.data ?? []).map((recipient) => ({
    value: recipient.id,
    label: recipient.email,
    hint: recipient.disabled ? "disabled" : !recipient.verified ? "unverified" : undefined,
    disabled: !alias.recipient_ids.includes(recipient.id) && (!recipient.verified || recipient.disabled),
  }));
  const labelOptions = (labels.data ?? []).map((label) => ({ value: label.id, label: label.name }));

  async function save(changes: AliasUpdate, message: string) {
    await update.mutateAsync({ id: alias.id, ...changes }).then(
      () => toast.success(message),
      (error: unknown) => toast.error(errorMessage(error, "Could not save")),
    );
  }

  async function runAction(action: "delete" | "forget" | "restore") {
    const mutation = { delete: remove, forget, restore }[action];
    const ok = await mutation.mutateAsync(alias.id).then(
      () => true,
      (error: unknown) => {
        toast.error(errorMessage(error));
        return false;
      },
    );
    setConfirm(null);
    if (!ok) return;
    toast.success({ delete: "Alias deleted", forget: "Alias forgotten", restore: "Alias restored" }[action]);
    if (action === "forget") onClose();
  }

  return (
    <div className="flex flex-col gap-6 px-4 pb-8">
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          ["Forwarded", alias.forwarded_count],
          ["Blocked", alias.blocked_count],
          ["Replies", alias.replied_count],
        ].map(([label, value]) => (
          <div key={label} className="rounded-md border p-2">
            <p className="text-lg font-semibold tabular-nums">{value}</p>
            <p className="text-xs text-muted-foreground">{label}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Created {formatDateTime(alias.created_at)} · last used {formatRelative(alias.last_used_at)}
      </p>

      {isEditable ? (
        <Section title="Behaviour">
          <ToggleRow
            id="alias-active"
            label="Active"
            hint="Inactive aliases accept mail and silently drop it."
            checked={alias.state === "active"}
            disabled={update.isPending}
            onChange={(active) => void save({ active }, active ? "Alias activated" : "Alias deactivated")}
          />
          <ToggleRow
            id="alias-replies"
            label="Allow replies"
            hint="Lets you reply and send from this alias."
            checked={alias.reply_enabled}
            disabled={update.isPending}
            onChange={(reply_enabled) => void save({ reply_enabled }, "Reply setting saved")}
          />
        </Section>
      ) : null}

      {isEditable ? (
        <Section title="Description">
          <Textarea
            aria-label="Description"
            value={description}
            maxLength={500}
            onChange={(event) => setDescription(event.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            className="self-end"
            disabled={update.isPending || description === (alias.description ?? "")}
            onClick={() => void save({ description: description.trim() || null }, "Description saved")}
          >
            Save description
          </Button>
        </Section>
      ) : null}

      {isEditable ? (
        <Section title="Forward to">
          <CheckList
            idPrefix="alias-recipient"
            options={recipientOptions}
            selected={recipientIds}
            onChange={setRecipientIds}
          />
          <p className="text-xs text-muted-foreground">None selected means your default recipient.</p>
          <Button
            size="sm"
            variant="outline"
            className="self-end"
            disabled={update.isPending}
            onClick={() => void save({ recipient_ids: recipientIds }, "Recipients saved")}
          >
            Save recipients
          </Button>
        </Section>
      ) : null}

      {isEditable && labelOptions.length > 0 ? (
        <Section title="Labels">
          <CheckList idPrefix="alias-label" options={labelOptions} selected={labelIds} onChange={setLabelIds} />
          <Button
            size="sm"
            variant="outline"
            className="self-end"
            disabled={update.isPending}
            onClick={() => void save({ label_ids: labelIds }, "Labels saved")}
          >
            Save labels
          </Button>
        </Section>
      ) : null}

      <Separator />
      <Section title="Contacts">
        <ContactsList aliasId={alias.id} aliasAddress={alias.address} readOnly={!isEditable} />
      </Section>

      <Separator />
      <Section title={isDeleted ? "Deleted alias" : "Danger zone"}>
        {isDeleted ? (
          <>
            <p className="text-sm text-muted-foreground">
              Deleted {formatDateTime(alias.deleted_at)}. Mail to it is rejected. You can restore it
              within 30 days, or forget it so it is unlinked from your account forever.
            </p>
            <div className="flex gap-2">
              <Button variant="outline" disabled={restore.isPending} onClick={() => void runAction("restore")}>
                Restore
              </Button>
              <Button variant="destructive" onClick={() => setConfirm("forget")}>
                Forget
              </Button>
            </div>
          </>
        ) : isEditable ? (
          <Button variant="destructive" className="self-start" onClick={() => setConfirm("delete")}>
            Delete alias
          </Button>
        ) : null}
      </Section>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={confirm === "forget" ? "Forget this alias?" : "Delete this alias?"}
        description={
          confirm === "forget"
            ? "It is unlinked from your account and can never be used again. This cannot be undone."
            : "Senders get a bounce. You can restore it within 30 days."
        }
        confirmLabel={confirm === "forget" ? "Forget forever" : "Delete"}
        destructive
        pending={remove.isPending || forget.isPending}
        onConfirm={() => confirm && void runAction(confirm)}
      />
    </div>
  );
}

/** Side sheet with everything about one alias. */
export function AliasDetailSheet({ aliasId, onClose }: AliasDetailSheetProps) {
  const alias = useAlias(aliasId);

  return (
    <Sheet open={aliasId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-1 pr-8 font-mono text-base break-all">
            {alias.data?.address ?? "Alias"}
            {alias.data ? <CopyButton value={alias.data.address} label="Copy address" /> : null}
          </SheetTitle>
          <SheetDescription asChild>
            <div>{alias.data ? <AliasStateBadge state={alias.data.state} /> : null}</div>
          </SheetDescription>
        </SheetHeader>
        {alias.isPending ? <Skeleton className="mx-4 h-40" /> : null}
        {alias.data ? <AliasDetails key={alias.data.id} alias={alias.data} onClose={onClose} /> : null}
      </SheetContent>
    </Sheet>
  );
}
