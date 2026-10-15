import { describe, expect, it } from "vitest";

import { INVITE_BODY, INVITE_SUBJECT, inviteMailto } from "./invite";
import { SITE } from "./site";

describe("inviteMailto", () => {
  it("addresses the invite inbox with the subject and body filled in", () => {
    const url = new URL(inviteMailto());
    expect(url.protocol).toBe("mailto:");
    expect(url.pathname).toBe(SITE.inviteEmail);
    expect(url.searchParams.get("subject")).toBe(INVITE_SUBJECT);
    expect(url.searchParams.get("body")).toBe(INVITE_BODY);
  });

  it("encodes spaces as %20 and line breaks as %0A, which every mail client accepts", () => {
    const url = inviteMailto();
    expect(url).not.toContain("+");
    expect(url).not.toContain(" ");
    expect(url).toContain("%0A");
  });

  it("asks for the details the invite flow needs", () => {
    expect(INVITE_BODY).toMatch(/^Name:/m);
    expect(INVITE_BODY).toMatch(/^Inbox to send the invite to/m);
    expect(INVITE_BODY).toMatch(/^Where you found closet-mail/m);
  });
});
