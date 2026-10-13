import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Label } from "@/lib/api";
import { http } from "@/lib/http";

export const LABELS_KEY = ["labels"] as const;

export function useLabels() {
  return useQuery({
    queryKey: LABELS_KEY,
    queryFn: async () => (await http.get<Label[]>("/labels")).data,
  });
}

export function useCreateLabel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string; color?: string | null }) =>
      (await http.post<Label>("/labels", input)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LABELS_KEY }),
  });
}
