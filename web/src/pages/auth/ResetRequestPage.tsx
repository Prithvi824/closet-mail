import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link } from "react-router";
import type { z } from "zod";

import { FormError } from "@/components/FormError";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import { useRequestReset } from "@/features/auth/api";
import { resetRequestSchema } from "@/features/auth/schemas";
import { errorMessage } from "@/lib/http";
import { AuthCard } from "@/pages/auth/AuthCard";

type ResetRequestValues = z.infer<typeof resetRequestSchema>;

export function ResetRequestPage() {
  const form = useForm<ResetRequestValues>({ resolver: zodResolver(resetRequestSchema) });
  const reset = useRequestReset();
  const backLink = <Link to="/login" className="underline-offset-4 hover:underline">Back to sign in</Link>;

  async function onSubmit(values: ResetRequestValues) {
    await reset.mutateAsync(values.email).catch(() => null);
  }

  if (reset.isSuccess) {
    return (
      <AuthCard title="Check your inbox" footer={backLink}>
        <p className="text-sm text-muted-foreground">
          If an account uses that address, a reset link is on its way. It is valid for one hour.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Reset password" description="We will email you a reset link." footer={backLink}>
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <FieldGroup>
          <FormError message={reset.error ? errorMessage(reset.error) : null} />
          <TextField
            id="email"
            label="Account email"
            type="email"
            autoComplete="email"
            autoFocus
            error={form.formState.errors.email?.message}
            {...form.register("email")}
          />
          <Button type="submit" disabled={reset.isPending}>
            {reset.isPending ? "Sending…" : "Send reset link"}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  );
}
