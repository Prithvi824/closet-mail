import { KeyRoundIcon, TrashIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useDeletePasskey, usePasskeys, useRegisterPasskey } from "@/features/settings/passkeys";
import { formatDateTime, formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

function registrationError(error: unknown): string {
  if (error instanceof Error && error.name === "NotAllowedError") return "Passkey setup was cancelled";
  if (error instanceof Error && error.name === "InvalidStateError") return "This device already has a passkey here";
  return errorMessage(error, "Could not add the passkey");
}

/** Passkeys as an alternative second factor: add (named per device) and remove. */
export function PasskeysCard() {
  const [name, setName] = useState("");
  const passkeys = usePasskeys();
  const register = useRegisterPasskey();
  const remove = useDeletePasskey();
  const supported = typeof window !== "undefined" && "PublicKeyCredential" in window;

  async function add(event: FormEvent) {
    event.preventDefault();
    const created = await register.mutateAsync(name.trim() || "Passkey").catch(() => null);
    if (!created) return;
    toast.success(`Passkey "${created.name}" added`);
    setName("");
  }

  async function drop(id: string) {
    await remove.mutateAsync(id).then(
      () => toast.success("Passkey removed"),
      (error: unknown) => toast.error(errorMessage(error)),
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Passkeys</CardTitle>
        <CardDescription>
          Use your device's fingerprint, face or security key as the second sign-in step.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ul className="divide-y rounded-md border empty:hidden">
          {passkeys.data?.map((passkey) => (
            <li key={passkey.id} className="flex items-center gap-3 px-3 py-2">
              <KeyRoundIcon className="size-4 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{passkey.name}</p>
                <p className="text-xs text-muted-foreground">
                  Added {formatDateTime(passkey.created_at)} · used {formatRelative(passkey.last_used_at)}
                </p>
              </div>
              <Button variant="ghost" size="icon-sm" aria-label={`Remove ${passkey.name}`} onClick={() => void drop(passkey.id)}>
                <TrashIcon />
              </Button>
            </li>
          ))}
        </ul>
        {supported ? (
          <form onSubmit={add} className="flex flex-col gap-2 sm:flex-row">
            <Input
              aria-label="Passkey name"
              placeholder="Name, e.g. Laptop"
              maxLength={60}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Button type="submit" variant="outline" disabled={register.isPending}>
              {register.isPending ? "Waiting for device…" : "Add passkey"}
            </Button>
          </form>
        ) : (
          <p className="text-sm text-muted-foreground">This browser does not support passkeys.</p>
        )}
        <FormError message={register.error ? registrationError(register.error) : null} />
      </CardContent>
    </Card>
  );
}
