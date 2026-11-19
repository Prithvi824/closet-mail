import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { SubdomainActivity } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

/** The open subdomain's activity over `days` days, with one page of recent mail. */
export function useActivity(days: number, page: number) {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: ["s", label, "activity", days, page],
    queryFn: async () =>
      (await http.get<SubdomainActivity>(sub(label, "/activity"), { params: { days, page } })).data,
    placeholderData: keepPreviousData,
  });
}
