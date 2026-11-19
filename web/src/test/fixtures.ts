import type { Alias, Me, Recipient, Subdomain, SubdomainSettings } from "@/lib/api";

export const me: Me = {
  id: "u1",
  username: "pia",
  email: "pia@example.com",
  role: "user",
  totp_enabled: false,
  banner_position: "top",
  alias_format: "words",
  strip_trackers: true,
  subdomain_catchall: false,
  created_at: "2026-10-01T10:00:00Z",
};

export const subdomainSettings: SubdomainSettings = {
  banner_position: "top",
  alias_format: "words",
  strip_trackers: true,
  subdomain_catchall: false,
};

export const recipient: Recipient = {
  id: "r1",
  email: "pia@example.com",
  verified: true,
  disabled: false,
  forward_by_default: true,
  pgp_fingerprint: null,
  pgp_protect_subject: false,
  created_at: "2026-10-01T10:00:00Z",
};

export function makeSubdomain(label: string, overrides: Partial<Subdomain> = {}): Subdomain {
  return {
    id: `id-${label}`,
    label,
    domain: `${label}.closetcompute.online`,
    display_name: null,
    notes: null,
    is_operator: false,
    suspended: false,
    retired: false,
    catchall: true,
    inbox_count: 1,
    default_inbox_count: 1,
    alias_count: 3,
    received_today: 2,
    sends_today: 1,
    send_share: 40,
    limits: null,
    status: {
      state: "ready",
      mx_ok: true,
      spf_ok: true,
      kv_ok: true,
      detail: null,
      checked_at: "2026-11-18T08:00:00Z",
      last_mail_at: "2026-11-18T07:00:00Z",
    },
    created_at: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}

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
