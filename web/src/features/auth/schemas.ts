import { z } from "zod";

/** Mirrors the backend password rule (10-256 characters). */
export const passwordSchema = z
  .string()
  .min(10, "At least 10 characters")
  .max(256, "At most 256 characters");

export const loginSchema = z.object({
  username: z.string().trim().min(1, "Enter your username"),
  password: z.string().min(1, "Enter your password"),
});

export const totpSchema = z.object({
  code: z
    .string()
    .trim()
    .min(6, "Enter the 6-digit code or a backup code")
    .max(16, "Too long"),
});

export const newPasswordSchema = z
  .object({ password: passwordSchema, confirm: z.string() })
  .refine((values) => values.password === values.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

export const inviteSchema = z
  .object({
    username: z
      .string()
      .trim()
      .toLowerCase()
      .regex(/^[a-z0-9-]{3,30}$/, "3-30 characters: letters, digits and hyphens"),
    password: passwordSchema,
    confirm: z.string(),
  })
  .refine((values) => values.password === values.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

export const resetRequestSchema = z.object({ email: z.email("Enter a valid email address") });

/** Only allow same-site relative redirects after login. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/aliases";
}
