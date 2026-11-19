import { screen, waitFor, within } from "@testing-library/react";

import { http } from "@/lib/http";
import { OverviewPage } from "@/pages/overview/OverviewPage";
import { overview } from "@/test/metrics";
import { renderPage } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn() } };
});

const get = vi.mocked(http.get);

describe("OverviewPage", () => {
  beforeEach(() => get.mockReset().mockResolvedValue({ data: overview } as never));

  it("shows totals, each subdomain and the top sender domains", async () => {
    renderPage(<OverviewPage />);
    const subdomains = await screen.findByRole("table", { name: "Mail per subdomain" });
    const acme = within(subdomains).getByRole("link", { name: "acme" });
    expect(acme).toHaveAttribute("href", "/s/acme/activity");
    expect(within(subdomains).getByText("Acme Ltd")).toBeInTheDocument();
    expect(screen.getByText("shop.example")).toBeInTheDocument();
    expect(screen.getByText("6 / 95")).toBeInTheDocument();
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/operator/overview", { params: { days: 30 } }),
    );
  });
});
