import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { QuarantineItem } from "@/lib/api";
import { http } from "@/lib/http";

export const QUARANTINE_KEY = ["quarantine"] as const;

/** Give the worker time to deliver a released message before refetching the list. */
const RELEASE_REFRESH_DELAY_MS = 5000;

export function useQuarantine() {
  return useQuery({
    queryKey: QUARANTINE_KEY,
    queryFn: async () => (await http.get<QuarantineItem[]>("/quarantine")).data,
  });
}

/** Queues delivery; the item disappears once the worker has delivered it. */
export function useReleaseQuarantined() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.post(`/quarantine/${id}/release`);
    },
    onSuccess: () => {
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: QUARANTINE_KEY }), RELEASE_REFRESH_DELAY_MS);
    },
  });
}

export function useDeleteQuarantined() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(`/quarantine/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUARANTINE_KEY }),
  });
}
