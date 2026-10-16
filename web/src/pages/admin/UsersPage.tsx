import { MoreHorizontalIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAdminUsers, useUpdateUser } from "@/features/admin/api";
import { useSession } from "@/features/auth/useSession";
import type { AdminUser, AdminUserUpdate } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/http";

export function UsersPage() {
  const [disabling, setDisabling] = useState<AdminUser | null>(null);
  const { user: me } = useSession();
  const users = useAdminUsers();
  const update = useUpdateUser();

  async function change(target: AdminUser, changes: AdminUserUpdate, message: string) {
    await update.mutateAsync({ id: target.id, ...changes }).then(
      () => toast.success(message),
      (error: unknown) => toast.error(errorMessage(error)),
    );
  }

  return (
    <>
      <PageHeader title="Users" description="Everyone with an account. Disabling a user signs them out and stops their mail." />
      {users.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {users.isError ? (
        <p className="text-sm text-destructive">{errorMessage(users.error, "Could not load users")}</p>
      ) : null}
      {users.data ? (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead className="w-px">Status</TableHead>
                <TableHead className="hidden w-px text-right sm:table-cell">Aliases</TableHead>
                <TableHead className="hidden w-px md:table-cell">Joined</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((user) => {
                const isSelf = user.id === me?.id;
                return (
                  <TableRow key={user.id}>
                    <TableCell className="w-full max-w-0">
                      <p className="truncate font-medium">{user.username}</p>
                      <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {isSelf ? <Badge variant="secondary">You</Badge> : null}
                        {user.role === "admin" ? <Badge>Admin</Badge> : null}
                        {user.disabled ? <Badge variant="destructive">Disabled</Badge> : null}
                        {user.limits ? <Badge variant="outline">Custom limits</Badge> : null}
                      </div>
                    </TableCell>
                    <TableCell className="hidden text-right tabular-nums sm:table-cell">{user.alias_count}</TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell">
                      {formatDateTime(user.created_at)}
                    </TableCell>
                    <TableCell>
                      {/* No actions on your own row: an admin must not disable or demote themselves. */}
                      {isSelf ? null : (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${user.username}`}>
                              <MoreHorizontalIcon />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onSelect={() =>
                                void change(
                                  user,
                                  { role: user.role === "admin" ? "user" : "admin" },
                                  user.role === "admin" ? "Admin rights removed" : "Made admin",
                                )
                              }
                            >
                              {user.role === "admin" ? "Remove admin" : "Make admin"}
                            </DropdownMenuItem>
                            {user.limits ? (
                              <DropdownMenuItem onSelect={() => void change(user, { limits: null }, "Limits reset")}>
                                Reset limits
                              </DropdownMenuItem>
                            ) : null}
                            {user.disabled ? (
                              <DropdownMenuItem onSelect={() => void change(user, { disabled: false }, "User enabled")}>
                                Enable
                              </DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem variant="destructive" onSelect={() => setDisabling(user)}>
                                Disable
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
      <ConfirmDialog
        open={disabling !== null}
        onOpenChange={(open) => !open && setDisabling(null)}
        title={`Disable ${disabling?.username ?? ""}?`}
        description="They are signed out, cannot sign in, and mail to their aliases is dropped until re-enabled."
        confirmLabel="Disable"
        destructive
        pending={update.isPending}
        onConfirm={() => {
          if (disabling) void change(disabling, { disabled: true }, "User disabled").then(() => setDisabling(null));
        }}
      />
    </>
  );
}
