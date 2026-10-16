import { KeyRoundIcon, PlusIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useRevokeToken, useTokens } from "@/features/tokens/api";
import { CreateTokenDialog } from "@/features/tokens/CreateTokenDialog";
import type { ApiToken } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

export function TokensPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const [revoking, setRevoking] = useState<ApiToken | null>(null);
  const tokens = useTokens();
  const revoke = useRevokeToken();

  async function confirmRevoke() {
    if (!revoking) return;
    await revoke.mutateAsync(revoking.id).then(
      () => toast.success("Token revoked"),
      (error: unknown) => toast.error(errorMessage(error)),
    );
    setRevoking(null);
  }

  return (
    <>
      <PageHeader
        title="API tokens"
        description="Let scripts manage your aliases. Tokens never reach settings, the blocklist or admin pages."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <PlusIcon /> New token
          </Button>
        }
      />
      {tokens.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {tokens.isError ? (
        <p className="text-sm text-destructive">{errorMessage(tokens.error, "Could not load tokens")}</p>
      ) : null}
      {tokens.data && tokens.data.length === 0 ? (
        <EmptyState icon={KeyRoundIcon} title="No tokens yet" />
      ) : null}
      {tokens.data && tokens.data.length > 0 ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Token</TableHead>
                <TableHead className="hidden md:table-cell">Permissions</TableHead>
                <TableHead className="hidden w-px lg:table-cell">Last used</TableHead>
                <TableHead className="w-px">Expires</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.data.map((token) => (
                <TableRow key={token.id}>
                  <TableCell className="max-w-0">
                    <p className="truncate font-medium">{token.name}</p>
                    <p className="font-mono text-xs text-muted-foreground">ma_{token.prefix}_…</p>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {token.scopes.map((scope) => (
                        <Badge key={scope} variant="outline">
                          {scope}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap text-muted-foreground lg:table-cell">
                    {formatRelative(token.last_used_at)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(token.expires_at)}>
                    {token.expires_at ? formatRelative(token.expires_at) : "never"}
                  </TableCell>
                  <TableCell>
                    <Button size="sm" variant="ghost" onClick={() => setRevoking(token)}>
                      Revoke
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      <CreateTokenDialog open={createOpen} onOpenChange={setCreateOpen} />
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={`Revoke "${revoking?.name ?? ""}"?`}
        description="Anything using it stops working immediately."
        confirmLabel="Revoke"
        destructive
        pending={revoke.isPending}
        onConfirm={() => void confirmRevoke()}
      />
    </>
  );
}
