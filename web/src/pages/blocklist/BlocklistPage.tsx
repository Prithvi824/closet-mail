import { BanIcon, XIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useAddBlock, useBlocklist, useRemoveBlock } from "@/features/blocklist/api";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/http";

export function BlocklistPage() {
  const [pattern, setPattern] = useState("");
  const entries = useBlocklist();
  const add = useAddBlock();
  const remove = useRemoveBlock();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const entry = await add.mutateAsync(pattern.trim()).catch(() => null);
    if (!entry) return;
    toast.success(`Blocked ${entry.pattern}`);
    setPattern("");
  }

  async function unblock(id: string, value: string) {
    await remove.mutateAsync(id).then(
      () => toast.success(`Unblocked ${value}`),
      (error: unknown) => toast.error(errorMessage(error)),
    );
  }

  return (
    <>
      <PageHeader
        title="Blocklist"
        description="Mail from these senders is dropped on every alias. A domain also covers its subdomains."
      />
      <form onSubmit={submit} className="mb-4 flex flex-col gap-2">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            aria-label="Address or domain to block"
            placeholder="spammer@example.com or example.com"
            value={pattern}
            onChange={(event) => {
              setPattern(event.target.value);
              add.reset();
            }}
          />
          <Button type="submit" disabled={!pattern.trim() || add.isPending}>
            <BanIcon /> Block
          </Button>
        </div>
        <FormError message={add.error ? errorMessage(add.error) : null} />
      </form>
      {entries.isPending ? <Skeleton className="h-16 w-full" /> : null}
      {entries.data && entries.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing blocked. You can also block a sender from the banner on forwarded mail.</p>
      ) : null}
      <ul className="divide-y rounded-lg border empty:hidden">
        {entries.data?.map((entry) => (
          <li key={entry.id} className="flex items-center gap-3 px-4 py-2">
            <span className="min-w-0 flex-1 truncate font-mono text-sm">{entry.pattern}</span>
            <Badge variant="outline">{entry.kind}</Badge>
            <span className="hidden text-xs text-muted-foreground sm:inline">{formatDateTime(entry.created_at)}</span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Unblock ${entry.pattern}`}
              disabled={remove.isPending}
              onClick={() => void unblock(entry.id, entry.pattern)}
            >
              <XIcon />
            </Button>
          </li>
        ))}
      </ul>
    </>
  );
}
