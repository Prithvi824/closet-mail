import { useQuery } from "@tanstack/react-query";

import type { Activity } from "@/lib/api";
import { http } from "@/lib/http";

export function useActivity(days: number) {
  return useQuery({
    queryKey: ["activity", days],
    queryFn: async () => (await http.get<Activity>("/me/activity", { params: { days } })).data,
  });
}
