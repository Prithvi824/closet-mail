import { MailPlusIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { CopyButton } from "@/components/CopyButton";
import { FormError } from "@/components/FormError";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useContacts, useCreateContact, useSetContactBlocked } from "@/features/aliases/api";
import type { Contact } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

interface ContactsListProps {
  aliasId: string;
  aliasAddress: string;
  /** Deleted aliases can't start conversations. */
  readOnly: boolean;
  /** The backend rejects replies and new conversations while replies are off. */
  replyEnabled: boolean;
}

interface ContactRowProps {
  contact: Contact;
  pending: boolean;
  onBlockedChange: (blocked: boolean) => void;
}

function ContactRow({ contact, pending, onBlockedChange }: ContactRowProps) {
  const switchId = `contact-blocked-${contact.id}`;
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{contact.name || contact.email}</p>
        <p className="truncate text-xs text-muted-foreground">
          {contact.name ? `${contact.email} · ` : ""}
          {contact.forwarded_count} in · {contact.replied_count} out · seen{" "}
          {formatRelative(contact.last_seen_at)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Label htmlFor={switchId} className="text-xs text-muted-foreground">
          Blocked
        </Label>
        <Switch
          id={switchId}
          checked={contact.blocked}
          disabled={pending}
          onCheckedChange={onBlockedChange}
        />
      </div>
    </li>
  );
}

/** Correspondents of an alias, with block toggles and "write to someone new". */
export function ContactsList({ aliasId, aliasAddress, readOnly, replyEnabled }: ContactsListProps) {
  const [email, setEmail] = useState("");
  const [started, setStarted] = useState<Contact | null>(null);
  const contacts = useContacts(aliasId);
  const createContact = useCreateContact(aliasId);
  const setBlocked = useSetContactBlocked(aliasId);

  async function startConversation(event: FormEvent) {
    event.preventDefault();
    const contact = await createContact.mutateAsync(email.trim()).catch(() => null);
    if (!contact) return;
    setStarted(contact);
    setEmail("");
  }

  function changeBlocked(contact: Contact, blocked: boolean) {
    setBlocked.mutate(
      { id: contact.id, blocked },
      { onError: (error: unknown) => toast.error(errorMessage(error, "Could not update the contact")) },
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {!readOnly ? (
        <form onSubmit={startConversation} className="flex flex-col gap-2">
          <Label htmlFor="new-contact">New message from this alias</Label>
          <div className="flex gap-2">
            <Input
              id="new-contact"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="someone@example.com"
              disabled={!replyEnabled}
            />
            <Button type="submit" variant="outline" disabled={!replyEnabled || !email.trim() || createContact.isPending}>
              <MailPlusIcon /> Get address
            </Button>
          </div>
          {!replyEnabled ? (
            <p className="text-xs text-muted-foreground">Turn on "Allow replies" to write from this alias.</p>
          ) : null}
          <FormError message={createContact.error ? errorMessage(createContact.error) : null} />
        </form>
      ) : null}
      {started ? (
        <Alert>
          <AlertTitle>Write to {started.email} through this address</AlertTitle>
          <AlertDescription className="flex flex-col gap-1">
            <span className="flex items-center gap-1 font-mono text-xs break-all">
              {started.token_address}
              <CopyButton value={started.token_address} label="Copy reply address" />
            </span>
            <span>
              Send from one of your recipients; it is delivered from {aliasAddress}.
            </span>
          </AlertDescription>
        </Alert>
      ) : null}
      {contacts.isPending ? <Skeleton className="h-10 w-full" /> : null}
      {contacts.isError ? (
        <p className="text-sm text-destructive">{errorMessage(contacts.error, "Could not load contacts")}</p>
      ) : null}
      {contacts.data && contacts.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No one has written to this alias yet.</p>
      ) : null}
      <ul className="divide-y">
        {contacts.data?.map((contact) => (
          <ContactRow
            key={contact.id}
            contact={contact}
            pending={setBlocked.isPending}
            onBlockedChange={(blocked) => changeBlocked(contact, blocked)}
          />
        ))}
      </ul>
    </div>
  );
}
