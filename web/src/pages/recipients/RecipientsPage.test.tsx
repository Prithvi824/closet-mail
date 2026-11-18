import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";

import { http } from "@/lib/http";
import { RecipientsPage } from "@/pages/recipients/RecipientsPage";
import { recipient } from "@/test/fixtures";
import { apiError, renderScoped } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const get = vi.mocked(http.get);
const patch = vi.mocked(http.patch);
const second = { ...recipient, id: "r2", email: "pia.work@example.org", forward_by_default: false };

describe("RecipientsPage", () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({ data: [recipient, second] } as never);
    patch.mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it("marks an inbox as default with its switch", async () => {
    patch.mockResolvedValueOnce({ data: { ...second, forward_by_default: true } });
    renderScoped(<RecipientsPage />, "pia", "inboxes");
    const toggle = await screen.findByRole("switch", { name: "Default inbox: pia.work@example.org" });
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/subdomains/pia/recipients/r2", { forward_by_default: true }));
  });

  it("shows why the last default inbox cannot be unmarked", async () => {
    const message = "Keep at least one default inbox: mark another inbox as default first";
    patch.mockRejectedValueOnce(apiError(422, message));
    renderScoped(<RecipientsPage />, "pia", "inboxes");
    await userEvent.click(await screen.findByRole("switch", { name: "Default inbox: pia@example.com" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
    expect(screen.getByText(/go to every default inbox/)).toBeInTheDocument();
  });
});
