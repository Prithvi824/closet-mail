import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { http } from "@/lib/http";
import { ActivityPage } from "@/pages/activity/ActivityPage";
import { activity } from "@/test/metrics";
import { renderScoped } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn() } };
});

const get = vi.mocked(http.get);

describe("ActivityPage", () => {
  beforeEach(() => get.mockReset().mockResolvedValue({ data: activity } as never));

  it("shows who sent each message and every inbox it went to", async () => {
    renderScoped(<ActivityPage />, "acme", "activity");
    const table = await screen.findByRole("table", { name: "Recent mail" });
    const bob = within(table).getAllByRole("row")[1];
    expect(within(bob).getByText("bob@shop.example")).toBeInTheDocument();
    expect(within(bob).getByText("owner@acme.example")).toBeInTheDocument();
    expect(within(bob).getByText("backup@acme.example")).toBeInTheDocument();
    expect(within(bob).getByText("bounced")).toBeInTheDocument();
    const dropped = within(table).getAllByRole("row")[2];
    expect(within(dropped).getByText("junk.example")).toBeInTheDocument();
    expect(within(dropped).getByText("unknown address")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Senders" })).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/subdomains/acme/activity", { params: { days: 30, page: 1 } });
  });

  it("pages through recent mail", async () => {
    renderScoped(<ActivityPage />, "acme", "activity");
    await userEvent.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/subdomains/acme/activity", { params: { days: 30, page: 2 } }),
    );
  });
});
