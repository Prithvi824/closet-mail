import { useState, type FormEvent } from "react";

import { CheckList } from "@/components/CheckList";
import { CopyButton } from "@/components/CopyButton";
import { FormError } from "@/components/FormError";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCreateToken } from "@/features/tokens/api";
import type { TokenScope } from "@/lib/api";
import { errorMessage } from "@/lib/http";

const SCOPE_OPTIONS: { value: TokenScope; label: string; hint: string }[] = [
  { value: "aliases:read", label: "Read aliases", hint: "list aliases, labels, contacts" },
  { value: "aliases:write", label: "Manage aliases", hint: "create, edit, delete" },
  { value: "contacts:write", label: "Manage contacts", hint: "block, start conversations" },
  { value: "recipients:read", label: "Read recipients", hint: "list forwarding addresses" },
];

const NEVER = "never";
const LIFETIMES = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
  { value: NEVER, label: "No expiry" },
];

interface CreateTokenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Create a token; its secret is shown in this dialog once and is gone when it closes. */
export function CreateTokenDialog({ open, onOpenChange }: CreateTokenDialogProps) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["aliases:read"]);
  const [lifetime, setLifetime] = useState("90");
  const [secret, setSecret] = useState<string | null>(null);
  const create = useCreateToken();

  function changeOpen(next: boolean) {
    if (!next) {
      setName("");
      setScopes(["aliases:read"]);
      setLifetime("90");
      setSecret(null);
      create.reset();
    }
    onOpenChange(next);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const created = await create
      .mutateAsync({
        name: name.trim(),
        scopes: scopes as TokenScope[],
        expires_in_days: lifetime === NEVER ? null : Number(lifetime),
      })
      .catch(() => null);
    if (created) setSecret(created.token);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="sm:max-w-lg">
        {secret ? (
          <>
            <DialogHeader>
              <DialogTitle>Copy your token</DialogTitle>
              <DialogDescription>This is the only time it is shown.</DialogDescription>
            </DialogHeader>
            <Alert>
              <AlertTitle>Token</AlertTitle>
              <AlertDescription className="flex items-center gap-1">
                <code data-testid="token-secret" className="font-mono text-xs break-all">
                  {secret}
                </code>
                <CopyButton value={secret} label="Copy token" />
              </AlertDescription>
            </Alert>
            <p className="text-sm text-muted-foreground">
              Send it as <code className="font-mono">Authorization: Bearer …</code>.
            </p>
            <DialogFooter>
              <Button onClick={() => changeOpen(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} noValidate>
            <DialogHeader>
              <DialogTitle>New API token</DialogTitle>
              <DialogDescription>For scripts and integrations. Grant only what they need.</DialogDescription>
            </DialogHeader>
            <FieldGroup className="py-4">
              <FormError message={create.error ? errorMessage(create.error) : null} />
              <Field>
                <FieldLabel htmlFor="token-name">Name</FieldLabel>
                <Input
                  id="token-name"
                  value={name}
                  maxLength={60}
                  placeholder="e.g. Password manager"
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel>Permissions</FieldLabel>
                <CheckList idPrefix="token-scope" options={SCOPE_OPTIONS} selected={scopes} onChange={setScopes} />
              </Field>
              <Field>
                <FieldLabel htmlFor="token-lifetime">Expires</FieldLabel>
                <Select value={lifetime} onValueChange={setLifetime}>
                  <SelectTrigger id="token-lifetime" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LIFETIMES.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </FieldGroup>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => changeOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || scopes.length === 0 || create.isPending}>
                Create token
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
