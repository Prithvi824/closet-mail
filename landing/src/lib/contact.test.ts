import { describe, expect, it } from "vitest";

import { CONTACT_BODY, CONTACT_SUBJECT, contactMailto } from "./contact";
import { SITE } from "./site";

describe("contactMailto", () => {
  it("addresses the contact inbox with the subject and body filled in", () => {
    const url = new URL(contactMailto());
    expect(url.protocol).toBe("mailto:");
    expect(url.pathname).toBe(SITE.contactEmail);
    expect(url.searchParams.get("subject")).toBe(CONTACT_SUBJECT);
    expect(url.searchParams.get("body")).toBe(CONTACT_BODY);
  });

  it("encodes spaces as %20 and line breaks as %0A, which every mail client accepts", () => {
    const url = contactMailto();
    expect(url).not.toContain("+");
    expect(url).not.toContain(" ");
    expect(url).toContain("%0A");
  });

  it("asks for what the operator needs to create a subdomain", () => {
    expect(CONTACT_BODY).toMatch(/^Name:/m);
    expect(CONTACT_BODY).toMatch(/^Label I'd like \(it becomes <label>\.closetcompute\.online\):/m);
    expect(CONTACT_BODY).toMatch(/^Inbox where my mail should go/m);
    expect(CONTACT_BODY).toMatch(/^Where you found closet-mail/m);
    expect(CONTACT_BODY).not.toMatch(/invite/i);
  });
});
