import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { Label } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const labelsKey = (label: string) => ["s", label, "labels"] as const;

export function useLabels() {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: labelsKey(label),
    queryFn: async () => (await http.get<Label[]>(sub(label, "/labels"))).data,
  });
}

export function useCreateLabel() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string; color?: string | null }) =>
      (await http.post<Label>(sub(label, "/labels"), input)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: labelsKey(label) }),
  });
}
