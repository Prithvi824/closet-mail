import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { CheckList } from "@/components/CheckList";
import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useCreateAlias } from "@/features/aliases/api";
import { localPartError } from "@/features/aliases/validation";
import { useMe } from "@/features/auth/api";
import { useRecipients } from "@/features/recipients/api";
import type { Alias, AliasCreate, AliasFormat } from "@/lib/api";
import { errorMessage } from "@/lib/http";

const ALIAS_DOMAIN = "closetcompute.online";

type Mode = "random" | "custom";

interface CreateAliasDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (alias: Alias) => void;
}

/** Create a generated alias (words or characters) or a custom one, optionally on the subdomain. */
export function CreateAliasDialog({ open, onOpenChange, onCreated }: CreateAliasDialogProps) {
  const [mode, setMode] = useState<Mode>("random");
  const [format, setFormat] = useState<AliasFormat | null>(null);
  const [localPart, setLocalPart] = useState("");
  const [onSubdomain, setOnSubdomain] = useState(false);
  const [description, setDescription] = useState("");
  const [recipientIds, setRecipientIds] = useState<string[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const me = useMe();
  const recipients = useRecipients();
  const create = useCreateAlias();
  const username = me.data?.username ?? "you";
  const chosenFormat = format ?? me.data?.alias_format ?? "words";
  const recipientOptions = (recipients.data ?? [])
    .filter((recipient) => recipient.verified && !recipient.disabled)
    .map((recipient) => ({
      value: recipient.id,
      label: recipient.email,
      hint: recipient.is_default ? "default" : undefined,
    }));

  function reset() {
    setMode("random");
    setFormat(null);
    setLocalPart("");
    setOnSubdomain(false);
    setDescription("");
    setRecipientIds([]);
    setLocalError(null);
    create.reset();
  }

  function changeOpen(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const payload: AliasCreate = {
      description: description.trim() || null,
      recipient_ids: recipientIds,
    };
    if (mode === "custom") {
      const problem = localPartError(localPart);
      setLocalError(problem);
      if (problem) return;
      Object.assign(payload, { local_part: localPart.trim().toLowerCase(), subdomain: onSubdomain });
    } else {
      payload.format = chosenFormat;
    }
    const alias = await create.mutateAsync(payload).catch(() => null);
    if (!alias) return;
    toast.success(`Created ${alias.address}`);
    changeOpen(false);
    onCreated(alias);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>New alias</DialogTitle>
            <DialogDescription>Mail to the alias is forwarded to your recipients.</DialogDescription>
          </DialogHeader>
          <FieldGroup className="py-4">
            <FormError message={create.error ? errorMessage(create.error, "Could not create the alias") : null} />
            <Tabs value={mode} onValueChange={(value) => setMode(value as Mode)}>
              <TabsList>
                <TabsTrigger value="random">Random</TabsTrigger>
                <TabsTrigger value="custom">Custom</TabsTrigger>
              </TabsList>
              <TabsContent value="random" className="pt-3">
                <Field>
                  <FieldLabel htmlFor="alias-format">Style</FieldLabel>
                  <Select value={chosenFormat} onValueChange={(value) => setFormat(value as AliasFormat)}>
                    <SelectTrigger id="alias-format" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="words">Words (e.g. maple.river42)</SelectItem>
                      <SelectItem value="chars">Characters (e.g. k3f9x2q8mz)</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </TabsContent>
              <TabsContent value="custom" className="pt-3">
                <Field data-invalid={localError ? true : undefined}>
                  <FieldLabel htmlFor="alias-local">Address</FieldLabel>
                  <div className="flex items-center gap-2">
                    <Input
                      id="alias-local"
                      value={localPart}
                      onChange={(event) => setLocalPart(event.target.value)}
                      aria-invalid={localError ? true : undefined}
                      placeholder="shopping"
                      autoComplete="off"
                    />
                    <Select
                      value={onSubdomain ? "subdomain" : "shared"}
                      onValueChange={(value) => setOnSubdomain(value === "subdomain")}
                    >
                      <SelectTrigger aria-label="Domain" className="w-auto max-w-56">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="shared">@{ALIAS_DOMAIN}</SelectItem>
                        <SelectItem value="subdomain">@{username}.{ALIAS_DOMAIN}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {localError ? <FieldError>{localError}</FieldError> : null}
                </Field>
              </TabsContent>
            </Tabs>
            <Field>
              <FieldLabel htmlFor="alias-description">Description</FieldLabel>
              <Textarea
                id="alias-description"
                value={description}
                maxLength={500}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Where you used it, e.g. Newsletter from example.com"
              />
            </Field>
            <Field>
              <FieldLabel>Forward to</FieldLabel>
              <FieldDescription>Leave empty to use your default recipient.</FieldDescription>
              <CheckList
                idPrefix="create-recipient"
                options={recipientOptions}
                selected={recipientIds}
                onChange={setRecipientIds}
                emptyText="No verified recipients yet."
              />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => changeOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create alias"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
