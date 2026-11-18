import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { RouterProvider, createMemoryRouter, type RouteObject } from "react-router";

/** Render routes in a memory router with a fresh, retry-free query client. */
export function renderRoutes(routes: RouteObject[], initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, queryClient };
}

/** Render a single element at "/". */
export function renderPage(element: ReactElement, path = "/") {
  return renderRoutes([{ path: "*", element }], path);
}

/** Render an element inside a subdomain route, e.g. /s/pia/aliases (useSubdomainLabel works). */
export function renderScoped(element: ReactElement, label = "pia", section = "page") {
  return renderRoutes([{ path: "/s/:label/*", element }], `/s/${label}/${section}`);
}

/** An axios-like error carrying an API error body. */
export function apiError(status: number, message: string) {
  return Object.assign(new Error(message), {
    isAxiosError: true,
    response: { status, data: { error: { code: "x", message } } },
  });
}
