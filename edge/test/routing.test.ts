/** Table-driven tests for the edge accept/reject contract. */
import { describe, expect, it } from "vitest";
import { MAX_RAW_SIZE, REJECT_NO_SUCH_USER, REJECT_TOO_LARGE, decide } from "../src/routing";
import { fakeKv } from "./helpers";

const KV_ENTRIES = {
  "a:active@closetcompute.online": "A",
  "a:paused@closetcompute.online": "I",
  "a:gone@closetcompute.online": "D",
  "r:abcdefghijklmnop": "V",
  "a:shop@alice.closetcompute.online": "A",
  "a:old@alice.closetcompute.online": "D",
  "a:old@bob.closetcompute.online": "D",
  "s:alice": "C",
};

const cases: Array<[string, string, "accept" | "reject"]> = [
  ["active shared alias", "active@closetcompute.online", "accept"],
  ["inactive shared alias (discarded later, not bounced)", "paused@closetcompute.online", "accept"],
  ["deleted shared alias", "gone@closetcompute.online", "reject"],
  ["unknown shared alias", "nobody@closetcompute.online", "reject"],
  ["mixed-case recipient is normalised", "Active@CLOSETCOMPUTE.online", "accept"],
  ["valid reply token", "abcdefghijklmnop@rp.closetcompute.online", "accept"],
  ["unknown reply token", "zzzzzzzzzzzzzzzz@rp.closetcompute.online", "reject"],
  ["known subdomain alias", "shop@alice.closetcompute.online", "accept"],
  ["deleted subdomain alias beats catch-all", "old@alice.closetcompute.online", "reject"],
  ["new subdomain address via catch-all", "anything@alice.closetcompute.online", "accept"],
  ["subdomain without catch-all", "anything@bob.closetcompute.online", "reject"],
  ["nested subdomain", "x@a.b.closetcompute.online", "reject"],
  ["foreign domain", "active@example.com", "reject"],
  ["lookalike domain", "active@evilclosetcompute.online", "reject"],
  ["malformed address", "no-at-sign", "reject"],
  ["empty local part", "@closetcompute.online", "reject"],
];

describe("decide", () => {
  it.each(cases)("%s", async (_name, rcpt, expected) => {
    const { kv } = fakeKv(KV_ENTRIES);
    const decision = await decide(rcpt, 1000, kv);
    expect(decision.action).toBe(expected);
    if (decision.action === "reject") expect(decision.reason).toBe(REJECT_NO_SUCH_USER);
  });

  it("rejects oversize messages before touching KV", async () => {
    const { kv, get } = fakeKv(KV_ENTRIES);
    const decision = await decide("active@closetcompute.online", MAX_RAW_SIZE + 1, kv);
    expect(decision).toEqual({ action: "reject", reason: REJECT_TOO_LARGE });
    expect(get).not.toHaveBeenCalled();
  });

  it("accepts exactly the size limit", async () => {
    const { kv } = fakeKv(KV_ENTRIES);
    expect((await decide("active@closetcompute.online", MAX_RAW_SIZE, kv)).action).toBe("accept");
  });

  it("reads KV with a 60s edge cache TTL", async () => {
    const { kv, get } = fakeKv(KV_ENTRIES);
    await decide("active@closetcompute.online", 10, kv);
    expect(get).toHaveBeenCalledWith("a:active@closetcompute.online", { cacheTtl: 60 });
  });
});
