import { z } from "zod";

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

/** Only allow same-site relative redirects after login. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/aliases";
}
