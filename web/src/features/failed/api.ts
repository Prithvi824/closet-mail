import { useQuery } from "@tanstack/react-query";

import type { FailedDelivery } from "@/lib/api";
import { http } from "@/lib/http";

export function useFailedDeliveries() {
  return useQuery({
    queryKey: ["failed-deliveries"],
    queryFn: async () => (await http.get<FailedDelivery[]>("/failed-deliveries")).data,
  });
}
