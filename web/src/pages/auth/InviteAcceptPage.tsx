import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import type { z } from "zod";

import { FormError } from "@/components/FormError";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import { useAcceptInvite } from "@/features/auth/api";
import { inviteSchema } from "@/features/auth/schemas";
import { errorMessage } from "@/lib/http";
import { AuthCard } from "@/pages/auth/AuthCard";

type InviteValues = z.infer<typeof inviteSchema>;

export function InviteAcceptPage() {
  const { token = "" } = useParams();
  const form = useForm<InviteValues>({ resolver: zodResolver(inviteSchema) });
  const accept = useAcceptInvite();
  const navigate = useNavigate();
  const { errors } = form.formState;

  async function onSubmit(values: InviteValues) {
    const result = await accept
      .mutateAsync({ token, username: values.username, password: values.password })
      .catch(() => null);
    if (!result) return;
    toast.success(`Account ${result.username} created. Sign in to continue.`);
    await navigate("/login", { replace: true });
  }

  return (
    <AuthCard
      title="Create your account"
      description="Your username also names your personal subdomain, e.g. you.closetcompute.online."
      footer={<Link to="/login" className="underline-offset-4 hover:underline">Already have an account?</Link>}
    >
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <FieldGroup>
          <FormError message={accept.error ? errorMessage(accept.error, "Invite could not be used") : null} />
          <TextField
            id="username"
            label="Username"
            autoComplete="username"
            autoFocus
            error={errors.username?.message}
            {...form.register("username")}
          />
          <TextField
            id="password"
            label="Password"
            type="password"
            autoComplete="new-password"
            description="At least 10 characters."
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
          <Button type="submit" disabled={accept.isPending}>
            {accept.isPending ? "Creating…" : "Create account"}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  );
}
