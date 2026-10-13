import { Navigate, Outlet, useLocation } from "react-router";

import { FullPageMessage } from "@/components/FullPageMessage";
import { useSession } from "@/features/auth/useSession";

interface RequireAuthProps {
  /** Only admins may enter (others see a not-allowed message). */
  admin?: boolean;
}

/** Route guard: renders child routes for signed-in users, otherwise redirects to /login. */
export function RequireAuth({ admin = false }: RequireAuthProps) {
  const location = useLocation();
  const { user, isLoading, isSignedOut, isAdmin } = useSession();

  if (isLoading) return <FullPageMessage title="Loading…" />;
  if (isSignedOut) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  if (!user) return <FullPageMessage title="Cannot reach the server" body="Try again shortly." />;
  if (admin && !isAdmin) return <FullPageMessage title="Not allowed" body="Admins only." />;
  return <Outlet />;
}
