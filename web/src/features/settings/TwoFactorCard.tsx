import QRCode from "qrcode";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { CopyButton } from "@/components/CopyButton";
import { FormError } from "@/components/FormError";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTotpDisable, useTotpEnable, useTotpSetup } from "@/features/settings/api";
import type { Me } from "@/lib/api";
import { errorMessage } from "@/lib/http";

interface TwoFactorCardProps {
  user: Me;
}

type Step = { kind: "idle" } | { kind: "scan"; qr: string; secret: string } | { kind: "codes"; codes: string[] };

/** The base32 secret inside an otpauth:// URI, for manual entry. */
function secretOf(uri: string): string {
  return new URL(uri).searchParams.get("secret") ?? "";
}

interface BackupCodesProps {
  codes: string[];
  onDone: () => void;
}

/** Shown exactly once, right after enabling. */
function BackupCodes({ codes, onDone }: BackupCodesProps) {
  const text = codes.join("\n");
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">
        Save these backup codes somewhere safe. Each works once if you lose your authenticator.
        <strong> They will not be shown again.</strong>
      </p>
      <ul aria-label="Backup codes" className="grid grid-cols-2 gap-1 rounded-md border bg-muted/50 p-3 font-mono text-sm">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <CopyButton value={text} label="Copy backup codes" />
        <span className="text-xs text-muted-foreground">Copy all</span>
        <Button className="ml-auto" onClick={onDone}>
          I saved them
        </Button>
      </div>
    </div>
  );
}

/** TOTP two-factor: set up with a QR code, confirm with a code, or turn off with the password. */
export function TwoFactorCard({ user }: TwoFactorCardProps) {
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const setup = useTotpSetup();
  const enable = useTotpEnable();
  const disable = useTotpDisable();

  async function start() {
    const result = await setup.mutateAsync().catch(() => null);
    if (!result) return;
    const qr = await QRCode.toDataURL(result.otpauth_uri, { margin: 1, width: 192 });
    setStep({ kind: "scan", qr, secret: secretOf(result.otpauth_uri) });
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    const result = await enable.mutateAsync(code.replace(/\s+/g, "")).catch(() => null);
    if (!result) return;
    setCode("");
    setStep({ kind: "codes", codes: result.backup_codes });
  }

  async function turnOff(event: FormEvent) {
    event.preventDefault();
    const ok = await disable.mutateAsync(password).then(
      () => true,
      () => false,
    );
    if (!ok) return;
    setPassword("");
    toast.success("Two-factor sign-in turned off");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Two-factor sign-in</CardTitle>
        <CardDescription>Ask for a code from an authenticator app when signing in.</CardDescription>
        <CardAction>
          <Badge variant={user.totp_enabled ? "default" : "secondary"}>{user.totp_enabled ? "On" : "Off"}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {step.kind === "codes" ? (
          <BackupCodes codes={step.codes} onDone={() => setStep({ kind: "idle" })} />
        ) : null}
        {step.kind === "idle" && !user.totp_enabled ? (
          <>
            <FormError message={setup.error ? errorMessage(setup.error) : null} />
            <Button className="self-start" disabled={setup.isPending} onClick={() => void start()}>
              Set up two-factor
            </Button>
          </>
        ) : null}
        {step.kind === "scan" ? (
          <form onSubmit={confirm} className="flex flex-col gap-4 sm:flex-row sm:items-start">
            <img src={step.qr} alt="QR code for your authenticator app" className="size-48 rounded-md border bg-white" />
            <div className="flex flex-1 flex-col gap-3">
              <p className="text-sm">Scan the code, or enter this key manually:</p>
              <p className="flex items-center gap-1 font-mono text-xs break-all">
                {step.secret}
                <CopyButton value={step.secret} label="Copy key" />
              </p>
              <Label htmlFor="totp-confirm">Code from the app</Label>
              <Input
                id="totp-confirm"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <FormError message={enable.error ? errorMessage(enable.error, "That code did not match") : null} />
              <div className="flex gap-2">
                <Button type="submit" disabled={enable.isPending || code.trim().length < 6}>
                  Turn on
                </Button>
                <Button type="button" variant="outline" onClick={() => setStep({ kind: "idle" })}>
                  Cancel
                </Button>
              </div>
            </div>
          </form>
        ) : null}
        {step.kind === "idle" && user.totp_enabled ? (
          <form onSubmit={turnOff} className="flex flex-col gap-2 sm:max-w-sm">
            <Label htmlFor="totp-password">Current password to turn it off</Label>
            <Input
              id="totp-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <FormError message={disable.error ? errorMessage(disable.error) : null} />
            <Button type="submit" variant="destructive" className="self-start" disabled={!password || disable.isPending}>
              Turn off
            </Button>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}
