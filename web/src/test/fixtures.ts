import type { Alias, Me, Recipient } from "@/lib/api";

export const me: Me = {
  id: "u1",
  username: "pia",
  email: "pia@example.com",
  role: "user",
  totp_enabled: false,
  default_recipient_id: "r1",
  banner_position: "top",
  alias_format: "words",
  strip_trackers: true,
  subdomain_catchall: false,
  created_at: "2026-10-01T10:00:00Z",
};

export const recipient: Recipient = {
  id: "r1",
  email: "pia@example.com",
  verified: true,
  disabled: false,
  is_default: true,
  pgp_fingerprint: null,
  pgp_protect_subject: false,
  created_at: "2026-10-01T10:00:00Z",
};

export function makeAlias(id: string, overrides: Partial<Alias> = {}): Alias {
  return {
    id,
    address: `${id}@closetcompute.online`,
    local_part: id,
    domain: "closetcompute.online",
    kind: "shared",
    state: "active",
    description: null,
    reply_enabled: true,
    recipient_ids: [],
    label_ids: [],
    forwarded_count: 0,
    blocked_count: 0,
    replied_count: 0,
    last_used_at: null,
    deleted_at: null,
    created_at: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}
