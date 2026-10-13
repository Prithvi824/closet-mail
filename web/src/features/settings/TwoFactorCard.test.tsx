import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TwoFactorCard } from "@/features/settings/TwoFactorCard";
import { http } from "@/lib/http";
import { me } from "@/test/fixtures";
import { renderPage } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn(async () => "data:image/png;base64,AAAA") } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const post = vi.mocked(http.post);
const CODES = ["aaaa-1111", "bbbb-2222"];

describe("TwoFactorCard", () => {
  it("sets up with a QR code and shows backup codes exactly once", async () => {
    post
      .mockResolvedValueOnce({ data: { otpauth_uri: "otpauth://totp/x:pia?secret=JBSWY3DPEHPK3PXP&issuer=x" } })
      .mockResolvedValueOnce({ data: { backup_codes: CODES } });
    renderPage(<TwoFactorCard user={me} />);
    await userEvent.click(screen.getByRole("button", { name: "Set up two-factor" }));
    expect(await screen.findByAltText(/QR code/)).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Code from the app"), "123 456");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(post).toHaveBeenLastCalledWith("/me/totp/enable", { code: "123456" });
    const list = await screen.findByRole("list", { name: "Backup codes" });
    expect(list).toHaveTextContent("aaaa-1111");
    await userEvent.click(screen.getByRole("button", { name: "I saved them" }));
    await waitFor(() => expect(screen.queryByText("aaaa-1111")).not.toBeInTheDocument());
  });

  it("asks for the password to turn it off", async () => {
    const del = vi.mocked(http.delete).mockResolvedValueOnce({ data: undefined });
    renderPage(<TwoFactorCard user={{ ...me, totp_enabled: true }} />);
    await userEvent.type(screen.getByLabelText(/Current password/), "secret-password");
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/me/totp", { data: { password: "secret-password" } }));
  });
});
