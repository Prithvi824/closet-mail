/**
 * Shared types for the edge-inbound Worker. `InboundJob` is the interface contract
 * with the backend processor: changing it requires a coordinated backend change.
 */

/** Queue message body sent for every accepted email (content type "json"). */
export interface InboundJob {
  v: 1;
  /** R2 object key, "in/YYYY/MM/DD/<uuid>.eml". */
  r2Key: string;
  /** Envelope sender, lowercased ("" for the null sender). */
  mailFrom: string;
  /** Envelope recipient, lowercased. */
  rcptTo: string;
  /** Raw message size in bytes. */
  rawSize: number;
  /** ISO-8601 UTC time the Worker accepted the message. */
  receivedAt: string;
}

/** Worker bindings declared in wrangler.toml. */
export interface Env {
  ALIASES: KVNamespace;
  INBOX: R2Bucket;
  INBOUND: Queue<InboundJob>;
}
