import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { SubdomainState } from "@/lib/api";
import { http } from "@/lib/http";
import { SubdomainsPage } from "@/pages/subdomains/SubdomainsPage";
import { makeSubdomain } from "@/test/fixtures";
import { renderPage } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const get = vi.mocked(http.get);
const post = vi.mocked(http.post);

describe("SubdomainsPage", () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({
      data: [makeSubdomain("pia", { is_operator: true }), makeSubdomain("acme")],
    } as never);
    post.mockReset();
  });

  it("creates a subdomain and shows the manual Cloudflare step", async () => {
    post.mockResolvedValueOnce({ data: makeSubdomain("beta") });
    renderPage(<SubdomainsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /new subdomain/i }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Label"), "beta");
    await userEvent.type(within(dialog).getByLabelText("Display name"), "Beta Co");
    await userEvent.type(within(dialog).getByLabelText("First inbox"), "owner@beta.example");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create subdomain" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/operator/subdomains", {
        label: "beta",
        display_name: "Beta Co",
        inbox_email: "owner@beta.example",
        notes: null,
      }),
    );
    const done = await screen.findByRole("dialog");
    expect(within(done).getByText(/Email Routing → Settings → Subdomains/)).toBeInTheDocument();
    expect(within(done).getByText("beta.closetcompute.online")).toBeInTheDocument();
    expect(within(done).getByText(/verification link was emailed to owner@beta.example/)).toBeInTheDocument();
  });

  it("labels every status", async () => {
    const states: SubdomainState[] = ["ready", "dns_missing", "no_inbox", "suspended", "retired", "unknown"];
    get.mockReset().mockResolvedValue({
      data: states.map((state, index) =>
        makeSubdomain(`s${index}`, { status: { ...makeSubdomain("x").status, state } }),
      ),
    } as never);
    renderPage(<SubdomainsPage />);
    for (const text of ["Ready", "DNS missing", "No inbox", "Suspended", "Retired", "Not checked"]) {
      expect(await screen.findByText(text)).toBeInTheDocument();
    }
  });

  it("asks before retiring, and never offers it for the operator's own subdomain", async () => {
    post.mockResolvedValueOnce({ data: makeSubdomain("acme", { retired: true }) });
    renderPage(<SubdomainsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Manage pia" }));
    const own = await screen.findByRole("dialog");
    expect(within(own).queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    expect(within(own).queryByRole("button", { name: "Suspend" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(await screen.findByRole("button", { name: "Manage acme" }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(within(sheet).getByRole("button", { name: "Retire" }));
    expect(post).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("dialog", { name: "Retire acme?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Retire subdomain" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/operator/subdomains/acme/retire"));
  });
});
