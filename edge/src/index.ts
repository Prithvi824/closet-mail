/**
 * edge-inbound Email Worker.
 * Gates each recipient against KV, buffers accepted raw mail in R2 and enqueues an
 * InboundJob for the home-server processor. Never parses bodies or logs addresses.
 */
import { decide } from "./routing";
import type { Env, InboundJob } from "./types";

export const TEMP_FAILURE = "451 4.3.0 Temporary failure, try again later";

/** Build the R2 key "in/YYYY/MM/DD/<uuid>.eml" for a UTC date. */
export function inboxKey(now: Date): string {
  const yyyy = now.getUTCFullYear().toString();
  const mm = (now.getUTCMonth() + 1).toString().padStart(2, "0");
  const dd = now.getUTCDate().toString().padStart(2, "0");
  return `in/${yyyy}/${mm}/${dd}/${crypto.randomUUID()}.eml`;
}

/** Normalise the envelope sender; the null sender ("<>") becomes "". */
function normaliseMailFrom(from: string): string {
  const value = from.trim().toLowerCase();
  return value === "<>" ? "" : value;
}

export default {
  async email(message: ForwardableEmailMessage, env: Env): Promise<void> {
    const decision = await decide(message.to, message.rawSize, env.ALIASES);
    if (decision.action === "reject") {
      message.setReject(decision.reason);
      return;
    }

    const now = new Date();
    const rcptTo = message.to.trim().toLowerCase();
    const r2Key = inboxKey(now);
    try {
      const raw = await new Response(message.raw).arrayBuffer();
      await env.INBOX.put(r2Key, raw, { customMetadata: { rcptTo } });
      const job: InboundJob = {
        v: 1,
        r2Key,
        mailFrom: normaliseMailFrom(message.from),
        rcptTo,
        rawSize: message.rawSize,
        receivedAt: now.toISOString(),
      };
      await env.INBOUND.send(job, { contentType: "json" });
    } catch (err) {
      // Sender's MTA will retry; log only the key and error type.
      console.error(JSON.stringify({ msg: "buffer_failed", r2Key, error: (err as Error).name }));
      message.setReject(TEMP_FAILURE);
    }
  },
} satisfies ExportedHandler<Env>;
