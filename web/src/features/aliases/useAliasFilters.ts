import { useSearchParams } from "react-router";

import { DEFAULT_FILTERS, STATE_FILTER_OPTIONS, type AliasFilters } from "@/features/aliases/types";
import type { AliasState } from "@/lib/api";

function isAliasState(value: string | null): value is AliasState {
  return value !== null && (STATE_FILTER_OPTIONS as string[]).includes(value);
}

/** Alias list filters stored in the URL (?q=&state=&label=&page=). */
export function useAliasFilters() {
  const [params, setParams] = useSearchParams();
  const state = params.get("state");
  const filters: AliasFilters = {
    q: params.get("q") ?? DEFAULT_FILTERS.q,
    state: isAliasState(state) ? state : DEFAULT_FILTERS.state,
    label: params.get("label") ?? DEFAULT_FILTERS.label,
    page: Math.max(1, Number(params.get("page")) || 1),
  };

  /** Apply changes; any change other than the page goes back to page 1. */
  function update(changes: Partial<AliasFilters>) {
    const next = { ...filters, ...("page" in changes ? {} : { page: 1 }), ...changes };
    const search = new URLSearchParams();
    if (next.q) search.set("q", next.q);
    if (next.state) search.set("state", next.state);
    if (next.label) search.set("label", next.label);
    if (next.page > 1) search.set("page", String(next.page));
    setParams(search, { replace: true });
  }

  return { filters, update };
}
