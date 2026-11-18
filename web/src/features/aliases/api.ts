import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PER_PAGE, type AliasFilters } from "@/features/aliases/types";
import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { Alias, AliasCreate, AliasPage, AliasUpdate, BulkAction, Contact } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const aliasKeys = {
  all: (label: string) => ["s", label, "aliases"] as const,
  list: (label: string, filters: AliasFilters) => ["s", label, "aliases", filters] as const,
  details: (label: string) => ["s", label, "alias"] as const,
  detail: (label: string, id: string) => ["s", label, "alias", id] as const,
  contacts: (label: string, aliasId: string) => ["s", label, "contacts", aliasId] as const,
};

/** Drop empty filters so the query string stays clean. */
function listParams(filters: AliasFilters) {
  return {
    page: filters.page,
    per_page: PER_PAGE,
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.state ? { state: filters.state } : {}),
    ...(filters.label ? { label: filters.label } : {}),
  };
}

export function useAliases(filters: AliasFilters) {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: aliasKeys.list(label, filters),
    queryFn: async () =>
      (await http.get<AliasPage>(sub(label, "/aliases"), { params: listParams(filters) })).data,
    placeholderData: keepPreviousData,
  });
}

export function useAlias(id: string | null) {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: aliasKeys.detail(label, id ?? ""),
    queryFn: async () => (await http.get<Alias>(sub(label, `/aliases/${id}`))).data,
    enabled: Boolean(id),
  });
}

/** Mutations on one alias refresh both the lists and that alias. */
function useAliasMutation<TInput, TResult>(label: string, request: (input: TInput) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: aliasKeys.all(label) });
      if (result && typeof result === "object" && "id" in result) {
        queryClient.setQueryData(aliasKeys.detail(label, String(result.id)), result);
      }
    },
  });
}

export function useCreateAlias() {
  const label = useSubdomainLabel();
  return useAliasMutation(
    label,
    async (input: AliasCreate) => (await http.post<Alias>(sub(label, "/aliases"), input)).data,
  );
}

export function useUpdateAlias() {
  const label = useSubdomainLabel();
  return useAliasMutation(
    label,
    async ({ id, ...changes }: AliasUpdate & { id: string }) =>
      (await http.patch<Alias>(sub(label, `/aliases/${id}`), changes)).data,
  );
}

export function useDeleteAlias() {
  const label = useSubdomainLabel();
  return useAliasMutation(
    label,
    async (id: string) => (await http.delete<Alias>(sub(label, `/aliases/${id}`))).data,
  );
}

export function useRestoreAlias() {
  const label = useSubdomainLabel();
  return useAliasMutation(
    label,
    async (id: string) => (await http.post<Alias>(sub(label, `/aliases/${id}/restore`))).data,
  );
}

export function useForgetAlias() {
  const label = useSubdomainLabel();
  return useAliasMutation(label, async (id: string) => {
    await http.post(sub(label, `/aliases/${id}/forget`));
    return null;
  });
}

/** Bulk changes touch many aliases, so every cached alias detail is refreshed too. */
export function useBulkAliases() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { ids: string[]; action: BulkAction }) =>
      (await http.post<{ changed: number }>(sub(label, "/aliases/bulk"), input)).data,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: aliasKeys.all(label) }),
        queryClient.invalidateQueries({ queryKey: aliasKeys.details(label) }),
      ]),
  });
}

export function useContacts(aliasId: string | null) {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: aliasKeys.contacts(label, aliasId ?? ""),
    queryFn: async () => (await http.get<Contact[]>(sub(label, `/aliases/${aliasId}/contacts`))).data,
    enabled: Boolean(aliasId),
  });
}

function useContactMutation<TInput>(
  label: string,
  aliasId: string,
  request: (input: TInput) => Promise<Contact>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: aliasKeys.contacts(label, aliasId) }),
  });
}

export function useCreateContact(aliasId: string) {
  const label = useSubdomainLabel();
  return useContactMutation(
    label,
    aliasId,
    async (email: string) => (await http.post<Contact>(sub(label, `/aliases/${aliasId}/contacts`), { email })).data,
  );
}

export function useSetContactBlocked(aliasId: string) {
  const label = useSubdomainLabel();
  return useContactMutation(
    label,
    aliasId,
    async (input: { id: string; blocked: boolean }) =>
      (await http.patch<Contact>(sub(label, `/contacts/${input.id}`), { blocked: input.blocked })).data,
  );
}
