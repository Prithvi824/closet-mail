import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRoundIcon } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { z } from "zod";

import { FormError } from "@/components/FormError";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";
import { FieldGroup, FieldSeparator } from "@/components/ui/field";
import { usePasskeyLogin, useTotpLogin } from "@/features/auth/api";
import { safeNext, totpSchema } from "@/features/auth/schemas";
import { errorMessage } from "@/lib/http";
import { AuthCard } from "@/pages/auth/AuthCard";

type TotpValues = z.infer<typeof totpSchema>;

/** Browsers reject a cancelled or timed-out passkey prompt with this error name. */
const PASSKEY_CANCELLED = "NotAllowedError";

function passkeyError(error: unknown): string {
  if (error instanceof Error && error.name === PASSKEY_CANCELLED) return "Passkey request was cancelled";
  return errorMessage(error, "Passkey sign-in failed");
}

/** Second sign-in step: authenticator code and/or passkey, depending on what the user set up. */
export function TotpPage() {
  const [params] = useSearchParams();
  const form = useForm<TotpValues>({ resolver: zodResolver(totpSchema) });
  const totp = useTotpLogin();
  const passkey = usePasskeyLogin();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const methods = (params.get("methods") ?? "totp").split(",");
  const hasTotp = methods.includes("totp");
  const hasPasskey = methods.includes("webauthn");
  const error = totp.error
    ? errorMessage(totp.error, "Invalid code")
    : passkey.error
      ? passkeyError(passkey.error)
      : null;

  async function submitCode(values: TotpValues) {
    passkey.reset();
    const ok = await totp.mutateAsync(values.code.replace(/\s+/g, "")).then(
      () => true,
      () => false,
    );
    if (ok) await navigate(next, { replace: true });
  }

  async function signInWithPasskey() {
    totp.reset();
    const ok = await passkey.mutateAsync().then(
      () => true,
      () => false,
    );
    if (ok) await navigate(next, { replace: true });
  }

  return (
    <AuthCard
      title="Second step"
      description={hasTotp ? "Enter the code from your authenticator app, or a backup code." : "Confirm it's you with your passkey."}
      footer={<Link to="/login" className="underline-offset-4 hover:underline">Back to sign in</Link>}
    >
      <FieldGroup>
        <FormError message={error} />
        {hasPasskey ? (
          <Button type="button" variant={hasTotp ? "outline" : "default"} disabled={passkey.isPending} onClick={() => void signInWithPasskey()}>
            <KeyRoundIcon /> {passkey.isPending ? "Waiting for passkey…" : "Use a passkey"}
          </Button>
        ) : null}
        {hasPasskey && hasTotp ? <FieldSeparator>or</FieldSeparator> : null}
        {hasTotp ? (
          <form onSubmit={form.handleSubmit(submitCode)} noValidate>
            <FieldGroup>
              <TextField
                id="code"
                label="Code"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus={!hasPasskey}
                error={form.formState.errors.code?.message}
                {...form.register("code")}
              />
              <Button type="submit" disabled={totp.isPending}>
                {totp.isPending ? "Checking…" : "Verify"}
              </Button>
            </FieldGroup>
          </form>
        ) : null}
      </FieldGroup>
    </AuthCard>
  );
}
