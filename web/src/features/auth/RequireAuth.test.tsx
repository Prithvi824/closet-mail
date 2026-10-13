import { screen } from "@testing-library/react";

import { RequireAuth } from "@/features/auth/RequireAuth";
import { http } from "@/lib/http";
import { me } from "@/test/fixtures";
import { apiError, renderRoutes } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn() } };
});

const get = vi.mocked(http.get);

const routes = [
  { path: "/login", element: <p>login page</p> },
  {
    element: <RequireAuth />,
    children: [
      { path: "/aliases", element: <p>aliases page</p> },
      { element: <RequireAuth admin />, children: [{ path: "/admin/users", element: <p>users page</p> }] },
    ],
  },
];

describe("RequireAuth", () => {
  it("sends signed-out visitors to login, remembering where they were going", async () => {
    get.mockRejectedValue(apiError(401, "Not signed in"));
    const { router } = renderRoutes(routes, "/aliases?q=shop");
    await screen.findByText("login page");
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent("/aliases?q=shop")}`);
  });

  it("keeps non-admins out of admin pages", async () => {
    get.mockResolvedValue({ data: me });
    renderRoutes(routes, "/admin/users");
    expect(await screen.findByText("Not allowed")).toBeInTheDocument();
    expect(screen.queryByText("users page")).not.toBeInTheDocument();
  });

  it("lets admins in", async () => {
    get.mockResolvedValue({ data: { ...me, role: "admin" } });
    renderRoutes(routes, "/admin/users");
    expect(await screen.findByText("users page")).toBeInTheDocument();
  });
});
