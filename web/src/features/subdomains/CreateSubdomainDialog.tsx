import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCreateSubdomain } from "@/features/subdomains/api";
import type { Subdomain } from "@/lib/api";
import { errorMessage } from "@/lib/http";
import { subdomainPage } from "@/lib/paths";

interface CreateSubdomainDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface SetupStepsProps {
  created: Subdomain;
  inbox: string;
}

/** What the operator still has to do by hand after creating a subdomain. */
function SetupSteps({ created, inbox }: SetupStepsProps) {
  return (
    <ol className="flex list-decimal flex-col gap-3 py-4 pl-5 text-sm">
      <li>
        In Cloudflare, open Email Routing → Settings → Subdomains and add{" "}
        <code className="rounded bg-muted px-1 font-mono">{created.domain}</code>.
      </li>
      <li>The verification link was emailed to {inbox}. Forwarding starts once it is clicked.</li>
      <li>Press “Check now” on the subdomain to confirm its DNS is ready.</li>
    </ol>
  );
}

/** Create a subdomain with its first inbox, then show the manual Cloudflare step. */
export function CreateSubdomainDialog({ open, onOpenChange }: CreateSubdomainDialogProps) {
  const [label, setLabel] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inbox, setInbox] = useState("");
  const [notes, setNotes] = useState("");
  const [created, setCreated] = useState<Subdomain | null>(null);
  const create = useCreateSubdomain();

  function changeOpen(next: boolean) {
    if (!next) {
      setLabel("");
      setDisplayName("");
      setInbox("");
      setNotes("");
      setCreated(null);
      create.reset();
    }
    onOpenChange(next);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = await create
      .mutateAsync({
        label: label.trim().toLowerCase(),
        display_name: displayName.trim() || null,
        inbox_email: inbox.trim(),
        notes: notes.trim() || null,
      })
      .catch(() => null);
    if (result) setCreated(result);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="sm:max-w-lg">
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>{created.label} created</DialogTitle>
              <DialogDescription>A few steps are left before mail flows.</DialogDescription>
            </DialogHeader>
            <SetupSteps created={created} inbox={inbox.trim()} />
            <DialogFooter>
              <Button variant="outline" asChild>
                <Link to={subdomainPage(created.label, "aliases")} onClick={() => changeOpen(false)}>
                  Open {created.label}
                </Link>
              </Button>
              <Button onClick={() => changeOpen(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} noValidate>
            <DialogHeader>
              <DialogTitle>New subdomain</DialogTitle>
              <DialogDescription>Each person you serve gets their own label.closetcompute.online.</DialogDescription>
            </DialogHeader>
            <FieldGroup className="py-4">
              <FormError message={create.error ? errorMessage(create.error, "Could not create the subdomain") : null} />
              <Field>
                <FieldLabel htmlFor="subdomain-label">Label</FieldLabel>
                <Input
                  id="subdomain-label"
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="acme"
                  autoComplete="off"
                  required
                />
                <FieldDescription>3–30 letters, digits or hyphens. It can't be changed later.</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="subdomain-name">Display name</FieldLabel>
                <Input id="subdomain-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="subdomain-inbox">First inbox</FieldLabel>
                <Input
                  id="subdomain-inbox"
                  type="email"
                  value={inbox}
                  onChange={(event) => setInbox(event.target.value)}
                  placeholder="person@example.com"
                  required
                />
                <FieldDescription>Gets a verification link; it becomes a default inbox.</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="subdomain-notes">Notes</FieldLabel>
                <Textarea id="subdomain-notes" value={notes} onChange={(event) => setNotes(event.target.value)} />
              </Field>
            </FieldGroup>
            <DialogFooter>
              <Button type="submit" disabled={create.isPending}>
                Create subdomain
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
