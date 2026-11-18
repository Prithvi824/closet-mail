import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SettingsUpdate, Subdomain, SubdomainCreate, SubdomainSettings, SubdomainUpdate } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const subdomainKeys = {
  all: ["operator", "subdomains"] as const,
  settings: (label: string) => ["s", label, "settings"] as const,
};

/** Every subdomain the operator runs, the operator's own first. */
export function useSubdomains() {
  return useQuery({
    queryKey: subdomainKeys.all,
    queryFn: async () => (await http.get<Subdomain[]>("/operator/subdomains")).data,
  });
}

/** Changes to one subdomain refresh the whole list (counts and status live there). */
function useSubdomainMutation<TInput>(request: (input: TInput) => Promise<Subdomain>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: subdomainKeys.all }),
  });
}

export function useCreateSubdomain() {
  return useSubdomainMutation(
    async (input: SubdomainCreate) => (await http.post<Subdomain>("/operator/subdomains", input)).data,
  );
}

export function useUpdateSubdomain() {
  return useSubdomainMutation(
    async ({ label, ...changes }: SubdomainUpdate & { label: string }) =>
      (await http.patch<Subdomain>(`/operator/subdomains/${label}`, changes)).data,
  );
}

export function useRetireSubdomain() {
  return useSubdomainMutation(
    async (label: string) => (await http.post<Subdomain>(`/operator/subdomains/${label}/retire`)).data,
  );
}

export function useCheckSubdomain() {
  return useSubdomainMutation(
    async (label: string) => (await http.post<Subdomain>(`/operator/subdomains/${label}/check`)).data,
  );
}

/** Forwarding preferences of one subdomain. */
export function useSubdomainSettings(label: string) {
  return useQuery({
    queryKey: subdomainKeys.settings(label),
    queryFn: async () => (await http.get<SubdomainSettings>(sub(label, "/settings"))).data,
  });
}

export function useUpdateSubdomainSettings(label: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (changes: SettingsUpdate) =>
      (await http.patch<SubdomainSettings>(sub(label, "/settings"), changes)).data,
    onSuccess: (settings) => {
      queryClient.setQueryData(subdomainKeys.settings(label), settings);
      return queryClient.invalidateQueries({ queryKey: subdomainKeys.all });
    },
  });
}
