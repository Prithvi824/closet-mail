import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { QuarantineItem } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const quarantineKey = (label: string) => ["s", label, "quarantine"] as const;

/** Give the worker time to deliver a released message before refetching the list. */
const RELEASE_REFRESH_DELAY_MS = 5000;

export function useQuarantine() {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: quarantineKey(label),
    queryFn: async () => (await http.get<QuarantineItem[]>(sub(label, "/quarantine"))).data,
  });
}

/** Queues delivery; the item disappears once the worker has delivered it. */
export function useReleaseQuarantined() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.post(sub(label, `/quarantine/${id}/release`));
    },
    onSuccess: () => {
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: quarantineKey(label) }), RELEASE_REFRESH_DELAY_MS);
    },
  });
}

export function useDeleteQuarantined() {
  const label = useSubdomainLabel();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(sub(label, `/quarantine/${id}`));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: quarantineKey(label) }),
  });
}
