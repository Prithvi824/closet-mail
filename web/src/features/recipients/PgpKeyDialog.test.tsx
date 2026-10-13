import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PgpKeyDialog } from "@/features/recipients/PgpKeyDialog";
import { http } from "@/lib/http";
import { recipient } from "@/test/fixtures";
import { apiError, renderPage } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), put: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const put = vi.mocked(http.put);
const KEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nmDMEabc\n-----END PGP PUBLIC KEY BLOCK-----";

describe("PgpKeyDialog", () => {
  beforeEach(() => put.mockReset());

  it("refuses text that is not an armored public key, without calling the API", async () => {
    renderPage(<PgpKeyDialog recipient={recipient} onClose={() => {}} />);
    await userEvent.type(screen.getByLabelText("Public key"), "hello");
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ASCII-armored public key");
    expect(put).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the key is rejected and keeps the dialog open", async () => {
    put.mockRejectedValueOnce(apiError(422, "This key has expired"));
    const onClose = vi.fn();
    renderPage(<PgpKeyDialog recipient={recipient} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText("Public key"));
    await userEvent.paste(KEY);
    await userEvent.click(screen.getByLabelText("Hide subject"));
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This key has expired");
    expect(put).toHaveBeenCalledWith(`/recipients/${recipient.id}/pgp`, {
      public_key: KEY,
      protect_subject: true,
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes after a successful upload", async () => {
    put.mockResolvedValueOnce({ data: { ...recipient, pgp_fingerprint: "ABCD" } });
    const onClose = vi.fn();
    renderPage(<PgpKeyDialog recipient={recipient} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText("Public key"));
    await userEvent.paste(KEY);
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
