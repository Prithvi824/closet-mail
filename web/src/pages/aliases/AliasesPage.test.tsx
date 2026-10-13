import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { http } from "@/lib/http";
import { AliasesPage } from "@/pages/aliases/AliasesPage";
import { makeAlias, me, recipient } from "@/test/fixtures";
import { renderPage } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const get = vi.mocked(http.get);
const post = vi.mocked(http.post);
const created = makeAlias("maple.river42");
let listed = [makeAlias("shop"), makeAlias("news")];

function routeGet(url: string) {
  const data: Record<string, unknown> = {
    "/me": me,
    "/labels": [],
    "/recipients": [recipient],
    "/aliases": { items: listed, total: listed.length, page: 1, per_page: 25 },
    [`/aliases/${created.id}`]: created,
    [`/aliases/${created.id}/contacts`]: [],
  };
  if (!(url in data)) return Promise.reject(new Error(`unexpected GET ${url}`));
  return Promise.resolve({ data: data[url] });
}

describe("AliasesPage", () => {
  beforeEach(() => {
    listed = [makeAlias("shop"), makeAlias("news")];
    get.mockReset().mockImplementation((url: string) => routeGet(url) as never);
    post.mockReset();
  });

  it("lists aliases", async () => {
    renderPage(<AliasesPage />);
    expect(await screen.findByText("shop@closetcompute.online")).toBeInTheDocument();
    expect(screen.getByText("news@closetcompute.online")).toBeInTheDocument();
  });

  it("creates a random alias in the user's style and opens it", async () => {
    post.mockResolvedValueOnce({ data: created });
    renderPage(<AliasesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /new alias/i }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Description"), "Newsletter");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create alias" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/aliases", {
        format: "words",
        description: "Newsletter",
        recipient_ids: [],
      }),
    );
    const sheet = await screen.findByRole("dialog");
    expect(await within(sheet).findByText("maple.river42@closetcompute.online")).toBeInTheDocument();
  });

  it("rejects an invalid custom address without calling the API", async () => {
    renderPage(<AliasesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /new alias/i }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("tab", { name: "Custom" }));
    await userEvent.type(within(dialog).getByLabelText("Address"), "-bad..name");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create alias" }));
    expect(await within(dialog).findByText(/start with a letter or digit/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("deactivates selected aliases in bulk", async () => {
    post.mockResolvedValueOnce({ data: { changed: 2 } });
    renderPage(<AliasesPage />);
    await userEvent.click(await screen.findByLabelText("Select shop@closetcompute.online"));
    await userEvent.click(screen.getByLabelText("Select news@closetcompute.online"));
    const toolbar = screen.getByRole("toolbar", { name: "Bulk actions" });
    expect(toolbar).toHaveTextContent("2 selected");
    await userEvent.click(within(toolbar).getByRole("button", { name: "Deactivate" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/aliases/bulk", { ids: ["shop", "news"], action: "deactivate" }),
    );
    await waitFor(() => expect(screen.queryByRole("toolbar")).not.toBeInTheDocument());
  });
});
