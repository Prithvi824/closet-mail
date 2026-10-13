import { useMe } from "@/features/auth/api";
import { errorStatus } from "@/lib/http";

/** Session state derived from GET /me. */
export function useSession() {
  const me = useMe();
  return {
    user: me.data,
    isLoading: me.isPending,
    isSignedOut: errorStatus(me.error) === 401,
    isAdmin: me.data?.role === "admin",
    error: me.error,
  };
}
