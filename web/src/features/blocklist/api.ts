import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { BlocklistEntry } from "@/lib/api";
import { http } from "@/lib/http";

export const BLOCKLIST_KEY = ["blocklist"] as const;

export function useBlocklist() {
  return useQuery({
    queryKey: BLOCKLIST_KEY,
    queryFn: async () => (await http.get<BlocklistEntry[]>("/blocklist")).data,
  });
}

export function useAddBlock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pattern: string) => (await http.post<BlocklistEntry>("/blocklist", { pattern })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: BLOCKLIST_KEY }),
  });
}

export function useRemoveBlock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(`/blocklist/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: BLOCKLIST_KEY }),
  });
}
