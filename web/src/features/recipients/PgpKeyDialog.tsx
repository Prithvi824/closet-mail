import { useState, type ChangeEvent, type FormEvent } from "react";
import { toast } from "sonner";

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
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSetPgpKey } from "@/features/recipients/api";
import type { Recipient } from "@/lib/api";
import { errorMessage } from "@/lib/http";

const PUBLIC_KEY_HEADER = "-----BEGIN PGP PUBLIC KEY BLOCK-----";
const MAX_KEY_BYTES = 64 * 1024;

interface PgpKeyDialogProps {
  recipient: Recipient | null;
  onClose: () => void;
}

/** Upload (paste or file), replace or remove a recipient's PGP public key. */
export function PgpKeyDialog({ recipient, onClose }: PgpKeyDialogProps) {
  const [armored, setArmored] = useState("");
  const [protectSubject, setProtectSubject] = useState(recipient?.pgp_protect_subject ?? false);
  const [localError, setLocalError] = useState<string | null>(null);
  const setKey = useSetPgpKey();
  const serverError = setKey.error ? errorMessage(setKey.error, "The key was not accepted") : null;

  function close() {
    setArmored("");
    setLocalError(null);
    setKey.reset();
    onClose();
  }

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_KEY_BYTES) {
      setLocalError("That file is too large to be a public key");
      return;
    }
    setArmored(await file.text());
    setLocalError(null);
  }

  async function save(publicKey: string | null) {
    if (!recipient) return;
    const ok = await setKey
      .mutateAsync({ id: recipient.id, public_key: publicKey, protect_subject: protectSubject })
      .then(
        () => true,
        () => false,
      );
    if (!ok) return;
    toast.success(publicKey ? "PGP key saved; forwards will be encrypted" : "PGP key removed");
    close();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const key = armored.trim();
    if (!key.startsWith(PUBLIC_KEY_HEADER)) {
      setLocalError("Paste an ASCII-armored public key (it starts with BEGIN PGP PUBLIC KEY BLOCK)");
      return;
    }
    setLocalError(null);
    await save(key);
  }

  return (
    <Dialog open={recipient !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent className="sm:max-w-xl">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>PGP encryption</DialogTitle>
            <DialogDescription>
              Mail forwarded to {recipient?.email} is encrypted to this key: the text, the HTML
              and every attachment.
            </DialogDescription>
          </DialogHeader>
          <FieldGroup className="py-4">
            <FormError message={localError ?? serverError} />
            {recipient?.pgp_fingerprint ? (
              <p className="text-sm">
                Current key: <span className="font-mono text-xs break-all">{recipient.pgp_fingerprint}</span>
              </p>
            ) : null}
            <Field>
              <FieldLabel htmlFor="pgp-key">Public key</FieldLabel>
              <Textarea
                id="pgp-key"
                className="h-40 font-mono text-xs"
                value={armored}
                onChange={(event) => setArmored(event.target.value)}
                placeholder={PUBLIC_KEY_HEADER}
              />
              <FieldDescription>Or choose a .asc file:</FieldDescription>
              <Input type="file" accept=".asc,.txt,.pub,.key" aria-label="Key file" onChange={readFile} />
            </Field>
            <div className="flex items-center justify-between gap-4">
              <div>
                <Label htmlFor="pgp-protect-subject">Hide subject</Label>
                <p className="text-xs text-muted-foreground">
                  The subject is moved inside the encrypted message; your inbox shows "...".
                </p>
              </div>
              <Switch id="pgp-protect-subject" checked={protectSubject} onCheckedChange={setProtectSubject} />
            </div>
          </FieldGroup>
          <DialogFooter className="gap-2">
            {recipient?.pgp_fingerprint ? (
              <Button
                type="button"
                variant="destructive"
                className="sm:mr-auto"
                disabled={setKey.isPending}
                onClick={() => void save(null)}
              >
                Remove key
              </Button>
            ) : null}
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" disabled={setKey.isPending || !armored.trim()}>
              {setKey.isPending ? "Checking…" : "Save key"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
