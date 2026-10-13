import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PER_PAGE, type AliasFilters } from "@/features/aliases/types";
import type { Alias, AliasCreate, AliasPage, AliasUpdate, BulkAction, Contact } from "@/lib/api";
import { http } from "@/lib/http";

export const aliasKeys = {
  all: ["aliases"] as const,
  list: (filters: AliasFilters) => ["aliases", filters] as const,
  detail: (id: string) => ["alias", id] as const,
  contacts: (aliasId: string) => ["contacts", aliasId] as const,
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
  return useQuery({
    queryKey: aliasKeys.list(filters),
    queryFn: async () =>
      (await http.get<AliasPage>("/aliases", { params: listParams(filters) })).data,
    placeholderData: keepPreviousData,
  });
}

export function useAlias(id: string | null) {
  return useQuery({
    queryKey: aliasKeys.detail(id ?? ""),
    queryFn: async () => (await http.get<Alias>(`/aliases/${id}`)).data,
    enabled: Boolean(id),
  });
}

/** Mutations on one alias refresh both the lists and that alias. */
function useAliasMutation<TInput, TResult>(request: (input: TInput) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: aliasKeys.all });
      if (result && typeof result === "object" && "id" in result) {
        queryClient.setQueryData(aliasKeys.detail(String(result.id)), result);
      }
    },
  });
}

export function useCreateAlias() {
  return useAliasMutation(async (input: AliasCreate) => (await http.post<Alias>("/aliases", input)).data);
}

export function useUpdateAlias() {
  return useAliasMutation(
    async ({ id, ...changes }: AliasUpdate & { id: string }) =>
      (await http.patch<Alias>(`/aliases/${id}`, changes)).data,
  );
}

export function useDeleteAlias() {
  return useAliasMutation(async (id: string) => (await http.delete<Alias>(`/aliases/${id}`)).data);
}

export function useRestoreAlias() {
  return useAliasMutation(async (id: string) => (await http.post<Alias>(`/aliases/${id}/restore`)).data);
}

export function useForgetAlias() {
  return useAliasMutation(async (id: string) => {
    await http.post(`/aliases/${id}/forget`);
    return null;
  });
}

export function useBulkAliases() {
  return useAliasMutation(
    async (input: { ids: string[]; action: BulkAction }) =>
      (await http.post<{ changed: number }>("/aliases/bulk", input)).data,
  );
}

export function useContacts(aliasId: string | null) {
  return useQuery({
    queryKey: aliasKeys.contacts(aliasId ?? ""),
    queryFn: async () => (await http.get<Contact[]>(`/aliases/${aliasId}/contacts`)).data,
    enabled: Boolean(aliasId),
  });
}

function useContactMutation<TInput>(aliasId: string, request: (input: TInput) => Promise<Contact>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: aliasKeys.contacts(aliasId) }),
  });
}

export function useCreateContact(aliasId: string) {
  return useContactMutation(
    aliasId,
    async (email: string) => (await http.post<Contact>(`/aliases/${aliasId}/contacts`, { email })).data,
  );
}

export function useSetContactBlocked(aliasId: string) {
  return useContactMutation(
    aliasId,
    async (input: { id: string; blocked: boolean }) =>
      (await http.patch<Contact>(`/contacts/${input.id}`, { blocked: input.blocked })).data,
  );
}
