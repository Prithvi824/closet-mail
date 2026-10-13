import type { AliasState } from "@/lib/api";

/** List filters; also the second part of the ["aliases", filters] query key. */
export interface AliasFilters {
  q: string;
  /** "" = active and inactive (the API default). */
  state: AliasState | "";
  label: string;
  page: number;
}

export const DEFAULT_FILTERS: AliasFilters = { q: "", state: "", label: "", page: 1 };

export const PER_PAGE = 25;

export const STATE_LABELS: Record<AliasState, string> = {
  active: "Active",
  inactive: "Inactive",
  deleted: "Deleted",
  forgotten: "Forgotten",
};
