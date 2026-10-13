import { PlusIcon, SearchIcon } from "lucide-react";
import { useEffect, useEffectEvent, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AliasDetailSheet } from "@/features/aliases/AliasDetailSheet";
import { AliasTable } from "@/features/aliases/AliasTable";
import { useAliases, useBulkAliases } from "@/features/aliases/api";
import { BulkActionsBar } from "@/features/aliases/BulkActionsBar";
import { CreateAliasDialog } from "@/features/aliases/CreateAliasDialog";
import { PER_PAGE, STATE_LABELS } from "@/features/aliases/types";
import { useAliasFilters } from "@/features/aliases/useAliasFilters";
import { useLabels } from "@/features/labels/api";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { AliasState, BulkAction } from "@/lib/api";
import { errorMessage } from "@/lib/http";

/** Radix Select needs a non-empty value for "no filter". */
const ANY = "any";

export function AliasesPage() {
  const { filters, update } = useAliasFilters();
  const [search, setSearch] = useState(filters.q);
  const [selected, setSelected] = useState<string[]>([]);
  const [openAliasId, setOpenAliasId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const debouncedSearch = useDebouncedValue(search.trim());
  const aliases = useAliases(filters);
  const labels = useLabels();
  const bulk = useBulkAliases();
  const items = aliases.data?.items ?? [];

  async function runBulk(action: BulkAction) {
    const result = await bulk.mutateAsync({ ids: selected, action }).catch((error: unknown) => {
      toast.error(errorMessage(error));
      return null;
    });
    if (!result) return;
    toast.success(`${result.changed} alias${result.changed === 1 ? "" : "es"} updated`);
    setSelected([]);
  }

  const applySearch = useEffectEvent((q: string) => {
    if (q !== filters.q) update({ q });
  });

  useEffect(() => applySearch(debouncedSearch), [debouncedSearch]);

  return (
    <>
      <PageHeader
        title="Aliases"
        description="Addresses you give out. Mail to them is forwarded to your recipients."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <PlusIcon /> New alias
          </Button>
        }
      />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search aliases"
            placeholder="Search address or description"
            className="pl-8"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <Select
          value={filters.state || ANY}
          onValueChange={(value) => update({ state: value === ANY ? "" : (value as AliasState) })}
        >
          <SelectTrigger aria-label="Filter by state" className="sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Active & inactive</SelectItem>
            {Object.entries(STATE_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {labels.data && labels.data.length > 0 ? (
          <Select
            value={filters.label || ANY}
            onValueChange={(value) => update({ label: value === ANY ? "" : value })}
          >
            <SelectTrigger aria-label="Filter by label" className="sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>All labels</SelectItem>
              {labels.data.map((label) => (
                <SelectItem key={label.id} value={label.id}>
                  {label.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      <BulkActionsBar
        count={selected.length}
        pending={bulk.isPending}
        onAction={(action) => void runBulk(action)}
        onClear={() => setSelected([])}
      />
      {aliases.isError ? (
        <p className="text-sm text-destructive">{errorMessage(aliases.error, "Could not load aliases")}</p>
      ) : (
        <AliasTable
          aliases={items}
          isLoading={aliases.isPending}
          selected={selected}
          onSelectedChange={setSelected}
          onOpen={(alias) => setOpenAliasId(alias.id)}
        />
      )}
      {aliases.data && aliases.data.total > PER_PAGE ? (
        <Pagination
          page={filters.page}
          perPage={PER_PAGE}
          total={aliases.data.total}
          onPageChange={(page) => {
            setSelected([]);
            update({ page });
          }}
        />
      ) : null}
      <CreateAliasDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(alias) => setOpenAliasId(alias.id)}
      />
      <AliasDetailSheet aliasId={openAliasId} onClose={() => setOpenAliasId(null)} />
    </>
  );
}
