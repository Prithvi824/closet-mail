import { act, screen } from "@testing-library/react";
import { useState } from "react";

import { SubdomainScope } from "@/features/subdomains/SubdomainScope";
import { renderRoutes } from "@/test/render";

let mounts = 0;

function Probe() {
  const [mountNumber] = useState(() => ++mounts);
  return <p>mount {mountNumber}</p>;
}

describe("SubdomainScope", () => {
  it("starts each subdomain's page fresh when the label changes", async () => {
    mounts = 0;
    const { router } = renderRoutes(
      [{ path: "/s/:label", element: <SubdomainScope />, children: [{ path: "aliases", element: <Probe /> }] }],
      "/s/acme/aliases",
    );
    expect(await screen.findByText("mount 1")).toBeInTheDocument();
    await act(() => router.navigate("/s/beta/aliases"));
    expect(await screen.findByText("mount 2")).toBeInTheDocument();
  });
});
