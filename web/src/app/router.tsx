import { Navigate, createBrowserRouter } from "react-router";

import { AppLayout } from "@/app/AppLayout";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { SubdomainScope } from "@/features/subdomains/SubdomainScope";
import { LoginPage } from "@/pages/auth/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

// Pages are code-split; each chunk loads on first navigation.
export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/totp", lazy: async () => ({ Component: (await import("@/pages/auth/TotpPage")).TotpPage }) },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <Navigate to="/overview" replace /> },
          {
            path: "/overview",
            lazy: async () => ({ Component: (await import("@/pages/overview/OverviewPage")).OverviewPage }),
          },
          {
            path: "/subdomains",
            lazy: async () => ({ Component: (await import("@/pages/subdomains/SubdomainsPage")).SubdomainsPage }),
          },
          {
            path: "/health",
            lazy: async () => ({ Component: (await import("@/pages/admin/HealthPage")).HealthPage }),
          },
          {
            path: "/account",
            lazy: async () => ({ Component: (await import("@/pages/account/AccountPage")).AccountPage }),
          },
          {
            path: "/s/:label",
            element: <SubdomainScope />,
            children: [
              { index: true, element: <Navigate to="aliases" replace /> },
              {
                path: "aliases",
                lazy: async () => ({ Component: (await import("@/pages/aliases/AliasesPage")).AliasesPage }),
              },
              {
                path: "inboxes",
                lazy: async () => ({ Component: (await import("@/pages/recipients/RecipientsPage")).RecipientsPage }),
              },
              {
                path: "quarantine",
                lazy: async () => ({ Component: (await import("@/pages/quarantine/QuarantinePage")).QuarantinePage }),
              },
              {
                path: "failed",
                lazy: async () => ({
                  Component: (await import("@/pages/failed/FailedDeliveriesPage")).FailedDeliveriesPage,
                }),
              },
              {
                path: "activity",
                lazy: async () => ({ Component: (await import("@/pages/activity/ActivityPage")).ActivityPage }),
              },
              {
                path: "blocklist",
                lazy: async () => ({ Component: (await import("@/pages/blocklist/BlocklistPage")).BlocklistPage }),
              },
              {
                path: "tokens",
                lazy: async () => ({ Component: (await import("@/pages/tokens/TokensPage")).TokensPage }),
              },
              {
                path: "settings",
                lazy: async () => ({ Component: (await import("@/pages/settings/SettingsPage")).SettingsPage }),
              },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
