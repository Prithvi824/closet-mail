import { useQuery } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { FailedDelivery } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export function useFailedDeliveries() {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: ["s", label, "failed-deliveries"],
    queryFn: async () => (await http.get<FailedDelivery[]>(sub(label, "/failed-deliveries"))).data,
  });
}
