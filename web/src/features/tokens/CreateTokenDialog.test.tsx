import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { CreateTokenDialog } from "@/features/tokens/CreateTokenDialog";
import { http } from "@/lib/http";
import { renderPage } from "@/test/render";

vi.mock("@/lib/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/http")>();
  return { ...original, http: { get: vi.fn(), post: vi.fn() } };
});

const post = vi.mocked(http.post);
const SECRET = "ma_abcd1234_0123456789abcdefghijklmnopqrstuv";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>open</Button>
      <CreateTokenDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

describe("CreateTokenDialog", () => {
  it("shows the secret once; reopening starts a fresh form without it", async () => {
    post.mockResolvedValueOnce({ data: { id: "t1", name: "cli", prefix: "abcd1234", scopes: ["aliases:read"], token: SECRET } });
    renderPage(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    await userEvent.type(screen.getByLabelText("Name"), "cli");
    await userEvent.click(screen.getByLabelText(/Manage aliases/));
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(await screen.findByTestId("token-secret")).toHaveTextContent(SECRET);
    expect(post).toHaveBeenCalledWith("/tokens", {
      name: "cli",
      scopes: ["aliases:read", "aliases:write"],
      expires_in_days: 90,
    });
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByTestId("token-secret")).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "open" }));
    expect(await screen.findByRole("button", { name: "Create token" })).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });
});
