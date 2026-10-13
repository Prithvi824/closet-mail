import { Navigate, createBrowserRouter } from "react-router";

import { AppLayout } from "@/app/AppLayout";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { LoginPage } from "@/pages/auth/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

// Pages are code-split; each chunk loads on first navigation.
export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/totp", lazy: async () => ({ Component: (await import("@/pages/auth/TotpPage")).TotpPage }) },
  {
    path: "/invite/:token",
    lazy: async () => ({ Component: (await import("@/pages/auth/InviteAcceptPage")).InviteAcceptPage }),
  },
  {
    path: "/reset",
    lazy: async () => ({ Component: (await import("@/pages/auth/ResetRequestPage")).ResetRequestPage }),
  },
  {
    path: "/reset/:token",
    lazy: async () => ({ Component: (await import("@/pages/auth/ResetConfirmPage")).ResetConfirmPage }),
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <Navigate to="/aliases" replace /> },
          {
            path: "/aliases",
            lazy: async () => ({ Component: (await import("@/pages/aliases/AliasesPage")).AliasesPage }),
          },
          {
            path: "/recipients",
            lazy: async () => ({ Component: (await import("@/pages/recipients/RecipientsPage")).RecipientsPage }),
          },
          {
            path: "/quarantine",
            lazy: async () => ({ Component: (await import("@/pages/quarantine/QuarantinePage")).QuarantinePage }),
          },
          {
            path: "/failed",
            lazy: async () => ({
              Component: (await import("@/pages/failed/FailedDeliveriesPage")).FailedDeliveriesPage,
            }),
          },
          {
            path: "/activity",
            lazy: async () => ({ Component: (await import("@/pages/activity/ActivityPage")).ActivityPage }),
          },
          {
            path: "/blocklist",
            lazy: async () => ({ Component: (await import("@/pages/blocklist/BlocklistPage")).BlocklistPage }),
          },
          {
            path: "/tokens",
            lazy: async () => ({ Component: (await import("@/pages/tokens/TokensPage")).TokensPage }),
          },
          {
            path: "/settings",
            lazy: async () => ({ Component: (await import("@/pages/settings/SettingsPage")).SettingsPage }),
          },
          {
            element: <RequireAuth admin />,
            children: [
              {
                path: "/admin/users",
                lazy: async () => ({ Component: (await import("@/pages/admin/UsersPage")).UsersPage }),
              },
              {
                path: "/admin/invites",
                lazy: async () => ({ Component: (await import("@/pages/admin/InvitesPage")).InvitesPage }),
              },
              {
                path: "/admin/health",
                lazy: async () => ({ Component: (await import("@/pages/admin/HealthPage")).HealthPage }),
              },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
