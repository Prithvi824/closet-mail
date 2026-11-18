import { useQuery } from "@tanstack/react-query";

import type { Overview } from "@/lib/api";
import { http } from "@/lib/http";

/** Mail across every subdomain over `days` days. */
export function useOverview(days: number) {
  return useQuery({
    queryKey: ["operator", "overview", days],
    queryFn: async () => (await http.get<Overview>("/operator/overview", { params: { days } })).data,
  });
}
