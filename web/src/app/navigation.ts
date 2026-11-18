import {
  ActivityIcon,
  AtSignIcon,
  BanIcon,
  GaugeIcon,
  GlobeIcon,
  HeartPulseIcon,
  InboxIcon,
  KeyRoundIcon,
  MailXIcon,
  SettingsIcon,
  ShieldAlertIcon,
  UserCogIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

/** Operator-wide pages. */
export const OPERATOR_NAV: NavItem[] = [
  { to: "/overview", label: "Overview", icon: GaugeIcon },
  { to: "/subdomains", label: "Subdomains", icon: GlobeIcon },
  { to: "/health", label: "Health", icon: HeartPulseIcon },
  { to: "/account", label: "Account", icon: UserCogIcon },
];

/** Sections of one subdomain; `to` is the segment after /s/:label/. */
export const SUBDOMAIN_NAV: NavItem[] = [
  { to: "aliases", label: "Aliases", icon: AtSignIcon },
  { to: "inboxes", label: "Inboxes", icon: InboxIcon },
  { to: "quarantine", label: "Quarantine", icon: ShieldAlertIcon },
  { to: "failed", label: "Failed deliveries", icon: MailXIcon },
  { to: "activity", label: "Activity", icon: ActivityIcon },
  { to: "blocklist", label: "Blocklist", icon: BanIcon },
  { to: "tokens", label: "API tokens", icon: KeyRoundIcon },
  { to: "settings", label: "Settings", icon: SettingsIcon },
];

export const SUBDOMAIN_SECTIONS = SUBDOMAIN_NAV.map((item) => item.to);
