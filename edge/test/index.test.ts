/** Tests for the email() handler: buffering, enqueueing and failure handling. */
import { describe, expect, it } from "vitest";
import worker, { TEMP_FAILURE, inboxKey } from "../src/index";
import { REJECT_NO_SUCH_USER } from "../src/routing";
import type { InboundJob } from "../src/types";
import { fakeEnv, fakeMessage } from "./helpers";

const KV = { "a:active@closetcompute.online": "A" };
const KEY_PATTERN = /^in\/\d{4}\/\d{2}\/\d{2}\/[0-9a-f-]{36}\.eml$/;

describe("email handler", () => {
  it("stores the raw message once and enqueues one valid InboundJob", async () => {
    const { env, put, send } = fakeEnv(KV);
    const { message, setReject, bytes } = fakeMessage({
      from: "Sender@Example.com",
      to: "Active@closetcompute.online",
    });

    await worker.email(message, env);

    expect(setReject).not.toHaveBeenCalled();
    expect(put).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledTimes(1);

    const [key, body, putOpts] = put.mock.calls[0]!;
    expect(key).toMatch(KEY_PATTERN);
    expect(new Uint8Array(body)).toEqual(bytes);
    expect(putOpts).toEqual({ customMetadata: { rcptTo: "active@closetcompute.online" } });

    const [job, sendOpts] = send.mock.calls[0]!;
    expect(sendOpts).toEqual({ contentType: "json" });
    const expected: Omit<InboundJob, "receivedAt"> = {
      v: 1,
      r2Key: key,
      mailFrom: "sender@example.com",
      rcptTo: "active@closetcompute.online",
      rawSize: bytes.byteLength,
    };
    expect(job).toMatchObject(expected);
    expect(new Date(job.receivedAt).toISOString()).toBe(job.receivedAt);
  });

  it("maps the null sender to an empty mailFrom", async () => {
    const { env, send } = fakeEnv(KV);
    const { message } = fakeMessage({ from: "<>", to: "active@closetcompute.online" });
    await worker.email(message, env);
    expect(send.mock.calls[0]![0].mailFrom).toBe("");
  });

  it("rejects unknown recipients without storing anything", async () => {
    const { env, put, send } = fakeEnv(KV);
    const { message, setReject } = fakeMessage({ from: "a@b.c", to: "nobody@closetcompute.online" });
    await worker.email(message, env);
    expect(setReject).toHaveBeenCalledWith(REJECT_NO_SUCH_USER);
    expect(put).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  it("temp-fails when R2 is unavailable", async () => {
    const { env, put, send } = fakeEnv(KV);
    put.mockRejectedValueOnce(new Error("r2 down"));
    const { message, setReject } = fakeMessage({ from: "a@b.c", to: "active@closetcompute.online" });
    await worker.email(message, env);
    expect(setReject).toHaveBeenCalledWith(TEMP_FAILURE);
    expect(send).not.toHaveBeenCalled();
  });

  it("temp-fails when the queue is unavailable", async () => {
    const { env, send } = fakeEnv(KV);
    send.mockRejectedValueOnce(new Error("queue down"));
    const { message, setReject } = fakeMessage({ from: "a@b.c", to: "active@closetcompute.online" });
    await worker.email(message, env);
    expect(setReject).toHaveBeenCalledWith(TEMP_FAILURE);
  });
});

describe("inboxKey", () => {
  it("uses the UTC date", () => {
    expect(inboxKey(new Date("2026-01-02T23:59:59Z"))).toMatch(/^in\/2026\/01\/02\//);
  });
});
