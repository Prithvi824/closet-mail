import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { DlqItem, Health } from "@/lib/api";
import { http } from "@/lib/http";

const HEALTH_REFRESH_MS = 30_000;

export const adminKeys = {
  health: ["admin", "health"] as const,
  dlq: ["admin", "dlq"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: adminKeys.health,
    queryFn: async () => (await http.get<Health>("/admin/health")).data,
    refetchInterval: HEALTH_REFRESH_MS,
  });
}

/** Peeking leases DLQ jobs for 30 s, so it only runs when asked. */
export function useDlq(enabled: boolean) {
  return useQuery({
    queryKey: adminKeys.dlq,
    queryFn: async () => (await http.get<DlqItem[]>("/admin/dlq")).data,
    enabled,
    staleTime: 0,
  });
}

export function useRetryDlq() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (r2Keys: string[] | null) =>
      (await http.post<{ moved: number }>("/admin/dlq/retry", { r2_keys: r2Keys })).data,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: adminKeys.health });
      queryClient.removeQueries({ queryKey: adminKeys.dlq });
    },
  });
}
