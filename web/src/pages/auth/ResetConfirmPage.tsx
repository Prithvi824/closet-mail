import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import type { z } from "zod";

import { FormError } from "@/components/FormError";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import { useConfirmReset } from "@/features/auth/api";
import { newPasswordSchema } from "@/features/auth/schemas";
import { errorMessage } from "@/lib/http";
import { AuthCard } from "@/pages/auth/AuthCard";

type NewPasswordValues = z.infer<typeof newPasswordSchema>;

export function ResetConfirmPage() {
  const { token = "" } = useParams();
  const form = useForm<NewPasswordValues>({ resolver: zodResolver(newPasswordSchema) });
  const confirm = useConfirmReset();
  const navigate = useNavigate();
  const { errors } = form.formState;

  async function onSubmit(values: NewPasswordValues) {
    const ok = await confirm.mutateAsync({ token, password: values.password }).then(
      () => true,
      () => false,
    );
    if (!ok) return;
    toast.success("Password changed. Sign in with your new password.");
    await navigate("/login", { replace: true });
  }

  return (
    <AuthCard title="Choose a new password" description="This signs you out everywhere else.">
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <FieldGroup>
          <FormError message={confirm.error ? errorMessage(confirm.error, "This link is invalid or has expired") : null} />
          <TextField
            id="password"
            label="New password"
            type="password"
            autoComplete="new-password"
            autoFocus
            error={errors.password?.message}
            {...form.register("password")}
          />
          <TextField
            id="confirm"
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            error={errors.confirm?.message}
            {...form.register("confirm")}
          />
          <Button type="submit" disabled={confirm.isPending}>
            {confirm.isPending ? "Saving…" : "Set password"}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  );
}
