import { useQuery } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { Activity } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export function useActivity(days: number) {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: ["s", label, "activity", days],
    queryFn: async () => (await http.get<Activity>(sub(label, "/activity"), { params: { days } })).data,
  });
}
