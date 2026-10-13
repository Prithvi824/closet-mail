/**
 * Accept/reject decision for an envelope recipient, based only on Workers KV.
 * KV is written by the backend (KvSync); keys:
 *   a:<address>  -> "A" active | "I" inactive | "D" deleted/forgotten
 *   r:<token>    -> "V" valid reverse-alias token
 *   s:<label>    -> "C" personal-subdomain catch-all enabled
 */

export const ALIAS_DOMAIN = "closetcompute.online";
export const REPLY_DOMAIN = `rp.${ALIAS_DOMAIN}`;
export const MAX_RAW_SIZE = 25 * 1024 * 1024;

export const REJECT_TOO_LARGE = "552 5.3.4 Message too large";
export const REJECT_NO_SUCH_USER = "550 5.1.1 Address does not exist";

/** KV cache TTL (seconds) at the edge; bounds how stale a decision can be. */
const KV_CACHE_TTL = 60;

export type EdgeDecision = { action: "accept" } | { action: "reject"; reason: string };

const ACCEPT: EdgeDecision = { action: "accept" };
const rejectNoSuchUser = (): EdgeDecision => ({ action: "reject", reason: REJECT_NO_SUCH_USER });

/** Split "local@domain" at the last "@"; returns null when either side is empty. */
function splitAddress(address: string): { local: string; domain: string } | null {
  const at = address.lastIndexOf("@");
  if (at <= 0 || at === address.length - 1) return null;
  return { local: address.slice(0, at), domain: address.slice(at + 1) };
}

/** Accept only when an alias key marks the address active or inactive. */
function aliasStateAccepts(state: string | null): boolean {
  return state === "A" || state === "I";
}

/**
 * Decide whether to accept mail for `rcptTo`.
 * Pure apart from KV reads; never throws for malformed input (it rejects instead).
 */
export async function decide(rcptTo: string, rawSize: number, kv: KVNamespace): Promise<EdgeDecision> {
  if (rawSize > MAX_RAW_SIZE) return { action: "reject", reason: REJECT_TOO_LARGE };

  const address = rcptTo.trim().toLowerCase();
  const parts = splitAddress(address);
  if (!parts) return rejectNoSuchUser();
  const { local, domain } = parts;
  const read = (key: string) => kv.get(key, { cacheTtl: KV_CACHE_TTL });

  // Reply tokens: <token>@rp.closetcompute.online
  if (domain === REPLY_DOMAIN) {
    return (await read(`r:${local}`)) !== null ? ACCEPT : rejectNoSuchUser();
  }

  // Shared aliases: <local>@closetcompute.online
  if (domain === ALIAS_DOMAIN) {
    return aliasStateAccepts(await read(`a:${address}`)) ? ACCEPT : rejectNoSuchUser();
  }

  // Personal subdomains: <local>@<username>.closetcompute.online (exactly one extra label)
  const suffix = `.${ALIAS_DOMAIN}`;
  if (domain.endsWith(suffix)) {
    const label = domain.slice(0, -suffix.length);
    if (!label || label.includes(".")) return rejectNoSuchUser();

    const state = await read(`a:${address}`);
    if (state !== null) return aliasStateAccepts(state) ? ACCEPT : rejectNoSuchUser();
    return (await read(`s:${label}`)) === "C" ? ACCEPT : rejectNoSuchUser();
  }

  return rejectNoSuchUser();
}
