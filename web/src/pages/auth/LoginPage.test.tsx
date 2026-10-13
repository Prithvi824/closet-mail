import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { http } from "@/lib/http";
import { LoginPage } from "@/pages/auth/LoginPage";
import { TotpPage } from "@/pages/auth/TotpPage";
import { apiError, renderRoutes } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), post: vi.fn() } };
});

vi.mock("@simplewebauthn/browser", () => ({
  startAuthentication: vi.fn(async () => ({ id: "cred" })),
}));

const post = vi.mocked(http.post);

const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/totp", element: <TotpPage /> },
  { path: "/aliases", element: <p>aliases page</p> },
];

async function signIn(username = "pia", password = "correct horse") {
  await userEvent.type(screen.getByLabelText("Username"), username);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("login flow", () => {
  beforeEach(() => post.mockReset());

  it("goes straight to the requested page when TOTP is off", async () => {
    post.mockResolvedValueOnce({ data: { mfa_required: false, mfa_methods: [] } });
    const { router } = renderRoutes(routes, "/login?next=%2Faliases");
    await signIn();
    await screen.findByText("aliases page");
    expect(post).toHaveBeenCalledWith("/auth/login", { username: "pia", password: "correct horse" });
    expect(router.state.location.pathname).toBe("/aliases");
  });

  it("asks for the TOTP code, then continues to the next page", async () => {
    post
      .mockResolvedValueOnce({ data: { mfa_required: true, mfa_methods: ["totp"] } })
      .mockResolvedValueOnce({ data: undefined });
    const { router } = renderRoutes(routes, "/login?next=%2Faliases");
    await signIn();
    await screen.findByText("Second step");
    expect(router.state.location.search).toBe("?next=%2Faliases&methods=totp");
    await userEvent.type(screen.getByLabelText("Code"), "123 456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await screen.findByText("aliases page");
    expect(post).toHaveBeenLastCalledWith("/auth/totp", { code: "123456" });
  });

  it("shows the server's error and stays on the page", async () => {
    post.mockRejectedValueOnce(apiError(401, "Invalid username or password"));
    renderRoutes(routes, "/login");
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
  });

  it("validates before calling the API", async () => {
    renderRoutes(routes, "/login");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your username")).toBeInTheDocument();
    await waitFor(() => expect(post).not.toHaveBeenCalled());
  });

  it("never redirects off-site after login", async () => {
    post.mockResolvedValueOnce({ data: { mfa_required: false, mfa_methods: [] } });
    const { router } = renderRoutes(routes, "/login?next=%2F%2Fevil.example");
    await signIn();
    await screen.findByText("aliases page");
    expect(router.state.location.pathname).toBe("/aliases");
  });
});

describe("passkey second step", () => {
  beforeEach(() => post.mockReset());

  it("offers only the passkey when that is the user's method, and signs in with it", async () => {
    post
      .mockResolvedValueOnce({ data: { mfa_required: true, mfa_methods: ["webauthn"] } })
      .mockResolvedValueOnce({ data: { options: { challenge: "abc", allowCredentials: [] } } })
      .mockResolvedValueOnce({ data: undefined });
    renderRoutes(routes, "/login?next=%2Faliases");
    await signIn();
    const button = await screen.findByRole("button", { name: /use a passkey/i });
    expect(screen.queryByLabelText("Code")).not.toBeInTheDocument();
    await userEvent.click(button);
    await screen.findByText("aliases page");
    expect(post).toHaveBeenCalledWith("/auth/webauthn/begin");
    expect(post).toHaveBeenLastCalledWith("/auth/webauthn/finish", { credential: { id: "cred" } });
  });
});
