import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CopyButton } from "@/components/CopyButton";
import { AliasStateBadge } from "@/features/aliases/AliasStateBadge";
import type { Alias } from "@/lib/api";
import { formatRelative } from "@/lib/format";

interface AliasTableProps {
  aliases: Alias[];
  isLoading: boolean;
  selected: string[];
  onSelectedChange: (ids: string[]) => void;
  onOpen: (alias: Alias) => void;
}

const SKELETON_ROWS = 5;

/** Alias list with row selection (for bulk actions); clicking a row opens its details. */
export function AliasTable({ aliases, isLoading, selected, onSelectedChange, onOpen }: AliasTableProps) {
  const allSelected = aliases.length > 0 && aliases.every((alias) => selected.includes(alias.id));

  function toggleAll(checked: boolean) {
    onSelectedChange(checked ? aliases.map((alias) => alias.id) : []);
  }

  function toggleOne(id: string, checked: boolean) {
    onSelectedChange(checked ? [...selected, id] : selected.filter((item) => item !== id));
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">
              <Checkbox
                aria-label="Select all"
                checked={allSelected}
                onCheckedChange={(checked) => toggleAll(checked === true)}
              />
            </TableHead>
            <TableHead>Address</TableHead>
            <TableHead className="hidden w-px sm:table-cell">State</TableHead>
            <TableHead className="hidden w-px text-right md:table-cell">Forwarded</TableHead>
            <TableHead className="hidden w-px text-right md:table-cell">Blocked</TableHead>
            <TableHead className="hidden w-px text-right md:table-cell">Replies</TableHead>
            <TableHead className="hidden w-px whitespace-nowrap lg:table-cell">Last used</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading
            ? Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <TableRow key={index}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))
            : null}
          {!isLoading && aliases.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                No aliases match.
              </TableCell>
            </TableRow>
          ) : null}
          {aliases.map((alias) => (
            <TableRow
              key={alias.id}
              className="cursor-pointer"
              data-state={selected.includes(alias.id) ? "selected" : undefined}
              onClick={() => onOpen(alias)}
            >
              <TableCell onClick={(event) => event.stopPropagation()}>
                <Checkbox
                  aria-label={`Select ${alias.address}`}
                  checked={selected.includes(alias.id)}
                  onCheckedChange={(checked) => toggleOne(alias.id, checked === true)}
                />
              </TableCell>
              <TableCell className="w-full max-w-0 min-w-48">
                <div className="flex items-center gap-1">
                  <span className="truncate font-mono text-sm">{alias.address}</span>
                  <CopyButton value={alias.address} label={`Copy ${alias.address}`} />
                </div>
                {alias.description ? (
                  <p className="truncate text-xs text-muted-foreground">{alias.description}</p>
                ) : null}
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <AliasStateBadge state={alias.state} />
              </TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">
                {alias.forwarded_count}
              </TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">
                {alias.blocked_count}
              </TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">
                {alias.replied_count}
              </TableCell>
              <TableCell className="hidden whitespace-nowrap text-muted-foreground lg:table-cell">
                {formatRelative(alias.last_used_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
