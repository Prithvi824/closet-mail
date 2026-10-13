import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { z } from "zod";

import { FormError } from "@/components/FormError";
import { TextField } from "@/components/TextField";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import { useLogin } from "@/features/auth/api";
import { loginSchema, safeNext } from "@/features/auth/schemas";
import { errorMessage } from "@/lib/http";
import { AuthCard } from "@/pages/auth/AuthCard";

type LoginValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const [params] = useSearchParams();
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });
  const login = useLogin();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const { errors } = form.formState;

  async function onSubmit(values: LoginValues) {
    const result = await login.mutateAsync(values).catch(() => null);
    if (!result) return;
    const methods = result.mfa_methods.join(",");
    const target = result.mfa_required
      ? `/totp?next=${encodeURIComponent(next)}&methods=${methods}`
      : next;
    await navigate(target, { replace: true });
  }

  return (
    <AuthCard
      title="Sign in"
      description="Use the username from your invite."
      footer={<Link to="/reset" className="underline-offset-4 hover:underline">Forgot your password?</Link>}
    >
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <FieldGroup>
          <FormError message={login.error ? errorMessage(login.error, "Sign in failed") : null} />
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
            autoComplete="current-password"
            error={errors.password?.message}
            {...form.register("password")}
          />
          <Button type="submit" disabled={login.isPending}>
            {login.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  );
}
