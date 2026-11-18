import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useCheckSubdomain, useRetireSubdomain, useUpdateSubdomain } from "@/features/subdomains/api";
import { StatusBadge } from "@/features/subdomains/StatusBadge";
import type { Subdomain } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";
import { subdomainPage } from "@/lib/paths";

const LIMIT_FIELDS = [
  { key: "sends_per_day", label: "Sends per day (share of the send cap)" },
  { key: "forwards_per_hour", label: "Forwards per hour" },
  { key: "replies_per_day", label: "Replies per day" },
] as const;

type Confirming = "suspend" | "retire" | null;

interface SubdomainSheetProps {
  subdomain: Subdomain | null;
  onClose: () => void;
}

interface SectionProps {
  title: string;
  children: ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  );
}

function check(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "not checked";
  return value ? "ok" : "missing";
}

interface StatusDetailProps {
  subdomain: Subdomain;
}

/** What the last routing check found. */
function StatusDetail({ subdomain }: StatusDetailProps) {
  const status = subdomain.status;
  const rows: [string, string][] = [
    ["MX records", check(status.mx_ok)],
    ["SPF record", check(status.spf_ok)],
    ["Edge catch-all flag", check(status.kv_ok)],
    ["Last mail", status.last_mail_at ? formatRelative(status.last_mail_at) : "none yet"],
    ["Checked", status.checked_at ? formatDateTime(status.checked_at) : "never"],
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([name, value]) => (
        <div key={name} className="contents">
          <dt className="text-muted-foreground">{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
      {status.detail ? <dd className="col-span-2 text-muted-foreground">{status.detail}</dd> : null}
    </dl>
  );
}

interface EditFormProps {
  subdomain: Subdomain;
}

/** Display name, notes and limits; saved together. */
function EditForm({ subdomain }: EditFormProps) {
  const [displayName, setDisplayName] = useState(subdomain.display_name ?? "");
  const [notes, setNotes] = useState(subdomain.notes ?? "");
  const [limits, setLimits] = useState<Record<string, string>>(
    Object.fromEntries(LIMIT_FIELDS.map(({ key }) => [key, String(subdomain.limits?.[key] ?? "")])),
  );
  const update = useUpdateSubdomain();

  async function save(event: FormEvent) {
    event.preventDefault();
    const chosen = Object.fromEntries(
      Object.entries(limits)
        .filter(([, value]) => value.trim() !== "")
        .map(([key, value]) => [key, Number(value)]),
    );
    const result = await update
      .mutateAsync({
        label: subdomain.label,
        display_name: displayName,
        notes,
        clear_limits: true,
        limits: Object.keys(chosen).length ? chosen : null,
      })
      .catch((error: unknown) => {
        toast.error(errorMessage(error, "Could not save"));
        return null;
      });
    if (result) toast.success("Saved");
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sheet-name">Display name</Label>
        <Input id="sheet-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sheet-notes">Notes</Label>
        <Textarea id="sheet-notes" value={notes} onChange={(event) => setNotes(event.target.value)} />
      </div>
      {LIMIT_FIELDS.map(({ key, label }) => (
        <div key={key} className="flex flex-col gap-1.5">
          <Label htmlFor={`sheet-${key}`}>{label}</Label>
          <Input
            id={`sheet-${key}`}
            type="number"
            min={1}
            placeholder={key === "sends_per_day" ? String(subdomain.send_share) : "default"}
            value={limits[key]}
            onChange={(event) => setLimits((current) => ({ ...current, [key]: event.target.value }))}
          />
        </div>
      ))}
      <p className="text-xs text-muted-foreground">Leave a limit empty to use the default.</p>
      <Button type="submit" disabled={update.isPending} className="self-start">
        Save
      </Button>
    </form>
  );
}

/** Manage one subdomain: status, details, limits, suspend/resume and retire. */
export function SubdomainSheet({ subdomain, onClose }: SubdomainSheetProps) {
  const [confirming, setConfirming] = useState<Confirming>(null);
  const update = useUpdateSubdomain();
  const retire = useRetireSubdomain();
  const recheck = useCheckSubdomain();
  const canChangeState = subdomain !== null && !subdomain.is_operator && !subdomain.retired;

  async function run(promise: Promise<unknown>, success: string) {
    await promise.then(
      () => toast.success(success),
      (error: unknown) => toast.error(errorMessage(error)),
    );
  }

  async function confirm() {
    if (!subdomain) return;
    if (confirming === "retire") {
      await run(retire.mutateAsync(subdomain.label), `${subdomain.label} retired`);
    } else {
      const suspended = !subdomain.suspended;
      const message = suspended ? `${subdomain.label} suspended` : `${subdomain.label} resumed`;
      await run(update.mutateAsync({ label: subdomain.label, suspended }), message);
    }
    setConfirming(null);
  }

  return (
    <Sheet open={subdomain !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {subdomain ? (
          <>
            <SheetHeader>
              <SheetTitle>{subdomain.label}</SheetTitle>
              <SheetDescription>{subdomain.domain}</SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-6 px-4 pb-6">
              <Section title="Status">
                <div className="flex items-center gap-3">
                  <StatusBadge state={subdomain.status.state} />
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={recheck.isPending}
                    onClick={() => void run(recheck.mutateAsync(subdomain.label), "Checked")}
                  >
                    Check now
                  </Button>
                </div>
                <StatusDetail subdomain={subdomain} />
                <Button variant="link" asChild className="self-start px-0">
                  <Link to={subdomainPage(subdomain.label, "aliases")} onClick={onClose}>
                    Open {subdomain.label}
                  </Link>
                </Button>
              </Section>
              <Separator />
              <Section title="Details and limits">
                <EditForm key={subdomain.id} subdomain={subdomain} />
              </Section>
              {canChangeState ? (
                <>
                  <Separator />
                  <Section title="Stop mail">
                    <div className="flex flex-wrap gap-2">
                      <Button variant="outline" onClick={() => setConfirming("suspend")}>
                        {subdomain.suspended ? "Resume" : "Suspend"}
                      </Button>
                      <Button variant="destructive" onClick={() => setConfirming("retire")}>
                        Retire
                      </Button>
                    </div>
                  </Section>
                </>
              ) : null}
            </div>
            <ConfirmDialog
              open={confirming !== null}
              onOpenChange={(open) => !open && setConfirming(null)}
              title={
                confirming === "retire"
                  ? `Retire ${subdomain.label}?`
                  : `${subdomain.suspended ? "Resume" : "Suspend"} ${subdomain.label}?`
              }
              description={
                confirming === "retire"
                  ? "Its aliases are forgotten (their addresses stay reserved) and its inboxes are turned off. This can't be undone."
                  : subdomain.suspended
                    ? "Mail to its aliases is forwarded again."
                    : "Mail to its aliases is dropped until you resume it."
              }
              confirmLabel={confirming === "retire" ? "Retire subdomain" : subdomain.suspended ? "Resume" : "Suspend"}
              destructive={confirming === "retire"}
              pending={update.isPending || retire.isPending}
              onConfirm={() => void confirm()}
            />
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
