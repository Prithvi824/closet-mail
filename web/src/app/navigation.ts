import {
  ActivityIcon,
  AtSignIcon,
  BanIcon,
  HeartPulseIcon,
  InboxIcon,
  KeyRoundIcon,
  MailPlusIcon,
  MailXIcon,
  SettingsIcon,
  ShieldAlertIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export const MAIN_NAV: NavItem[] = [
  { to: "/aliases", label: "Aliases", icon: AtSignIcon },
  { to: "/recipients", label: "Recipients", icon: InboxIcon },
  { to: "/quarantine", label: "Quarantine", icon: ShieldAlertIcon },
  { to: "/failed", label: "Failed deliveries", icon: MailXIcon },
  { to: "/activity", label: "Activity", icon: ActivityIcon },
  { to: "/blocklist", label: "Blocklist", icon: BanIcon },
  { to: "/tokens", label: "API tokens", icon: KeyRoundIcon },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export const ADMIN_NAV: NavItem[] = [
  { to: "/admin/users", label: "Users", icon: UsersIcon },
  { to: "/admin/invites", label: "Invites", icon: MailPlusIcon },
  { to: "/admin/health", label: "Health", icon: HeartPulseIcon },
];
