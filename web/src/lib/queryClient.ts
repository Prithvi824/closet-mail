import { QueryClient } from "@tanstack/react-query";

import { errorStatus } from "@/lib/http";

const MAX_RETRIES = 2;

/** Shared query client: no retries on 4xx (they will not succeed on retry). */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        const status = errorStatus(error);
        if (status !== undefined && status < 500) return false;
        return failureCount < MAX_RETRIES;
      },
    },
  },
});
