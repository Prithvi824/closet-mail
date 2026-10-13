/** Test doubles for Workers bindings and the inbound email message. */
import { vi } from "vitest";
import type { Env, InboundJob } from "../src/types";

/** In-memory KV exposing only `get`, recording the options it was called with. */
export function fakeKv(entries: Record<string, string>) {
  const get = vi.fn(async (key: string, _opts?: unknown) => entries[key] ?? null);
  return { kv: { get } as unknown as KVNamespace, get };
}

/** Env with recording R2 `put` and Queue `send` mocks. */
export function fakeEnv(entries: Record<string, string>) {
  const { kv } = fakeKv(entries);
  const put = vi.fn(async (_key: string, _value: ArrayBuffer, _opts?: unknown) => ({}));
  const send = vi.fn(async (_job: InboundJob, _opts?: unknown) => undefined);
  const env = {
    ALIASES: kv,
    INBOX: { put } as unknown as R2Bucket,
    INBOUND: { send } as unknown as Queue<InboundJob>,
  } satisfies Env;
  return { env, put, send };
}

/** Minimal ForwardableEmailMessage carrying `body` as the raw stream. */
export function fakeMessage(opts: { from: string; to: string; body?: string; rawSize?: number }) {
  const bytes = new TextEncoder().encode(opts.body ?? "Subject: hi\r\n\r\nhello\r\n");
  const setReject = vi.fn((_reason: string) => undefined);
  const message = {
    from: opts.from,
    to: opts.to,
    raw: new Response(bytes).body!,
    rawSize: opts.rawSize ?? bytes.byteLength,
    headers: new Headers(),
    setReject,
  } as unknown as ForwardableEmailMessage;
  return { message, setReject, bytes };
}
