import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiToken, ApiTokenCreated, TokenCreate } from "@/lib/api";
import { http } from "@/lib/http";

export const TOKENS_KEY = ["tokens"] as const;

export function useTokens() {
  return useQuery({
    queryKey: TOKENS_KEY,
    queryFn: async () => (await http.get<ApiToken[]>("/tokens")).data,
  });
}

export function useCreateToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: TokenCreate) => (await http.post<ApiTokenCreated>("/tokens", input)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TOKENS_KEY }),
  });
}

export function useRevokeToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(`/tokens/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TOKENS_KEY }),
  });
}
