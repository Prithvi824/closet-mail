import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { ApiToken, ApiTokenCreated, TokenCreate } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const tokensKey = (label: string) => ["s", label, "tokens"] as const;

export function useTokens() {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: tokensKey(label),
    queryFn: async () => (await http.get<ApiToken[]>(sub(label, "/tokens"))).data,
  });
}

export function useCreateToken() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: TokenCreate) => (await http.post<ApiTokenCreated>(sub(label, "/tokens"), input)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tokensKey(label) }),
  });
}

export function useRevokeToken() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(sub(label, `/tokens/${id}`));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tokensKey(label) }),
  });
}
