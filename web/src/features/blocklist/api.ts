import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { BlocklistEntry } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const blocklistKey = (label: string) => ["s", label, "blocklist"] as const;

export function useBlocklist() {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: blocklistKey(label),
    queryFn: async () => (await http.get<BlocklistEntry[]>(sub(label, "/blocklist"))).data,
  });
}

export function useAddBlock() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pattern: string) => (await http.post<BlocklistEntry>(sub(label, "/blocklist"), { pattern })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: blocklistKey(label) }),
  });
}

export function useRemoveBlock() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(sub(label, `/blocklist/${id}`));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: blocklistKey(label) }),
  });
}
