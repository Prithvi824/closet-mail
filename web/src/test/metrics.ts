import type { MailEvent, Overview, OutcomeTotals, SubdomainActivity } from "@/lib/api";

export const totals: OutcomeTotals = {
  received: 4,
  delivered: 3,
  quarantined: 1,
  blocked: 0,
  discarded: 0,
  replies: 2,
};

const daily = [
  { day: "2026-11-17", received: 1, delivered: 1, replies: 0 },
  { day: "2026-11-18", received: 3, delivered: 2, replies: 2 },
];

export const overview: Overview = {
  days: 7,
  totals,
  daily,
  per_subdomain: [
    { label: "pia", display_name: null, totals, sends_today: 5, send_share: 40 },
    { label: "acme", display_name: "Acme Ltd", totals: { ...totals, received: 1 }, sends_today: 1, send_share: 40 },
  ],
  top_sender_domains: [
    { key: "shop.example", count: 3 },
    { key: "junk.example", count: 1 },
  ],
  sends_today: 6,
  send_cap: 95,
};

export const bobMail: MailEvent = {
  id: "m1",
  received_at: "2026-11-18T09:00:00Z",
  kind: "forward",
  outcome: "delivered",
  reason: null,
  alias_address: "acme-shop@closetcompute.online",
  sender: "bob@shop.example",
  sender_domain: "shop.example",
  destinations: [
    { inbox: "owner@acme.example", status: "delivered" },
    { inbox: "backup@acme.example", status: "bounced" },
  ],
  spam_score: 0.5,
  size_bytes: 1200,
};

export const activity: SubdomainActivity = {
  days: 30,
  totals,
  daily,
  top_sender_domains: [{ key: "shop.example", count: 3 }],
  top_senders: [{ key: "bob@shop.example", count: 2 }],
  per_alias: [{ key: "acme-shop@closetcompute.online", count: 3 }],
  per_inbox: [{ key: "owner@acme.example", count: 3 }],
  recent: [
    bobMail,
    {
      ...bobMail,
      id: "m2",
      outcome: "discarded",
      reason: "unknown_alias",
      alias_address: null,
      sender: null,
      sender_domain: "junk.example",
      destinations: [],
    },
  ],
  page: 1,
  has_more: true,
};
