import { Badge } from "@/components/ui/badge";
import type { SubdomainState } from "@/lib/api";

const STATE_LABELS: Record<SubdomainState, string> = {
  ready: "Ready",
  dns_missing: "DNS missing",
  no_inbox: "No inbox",
  suspended: "Suspended",
  retired: "Retired",
  unknown: "Not checked",
};

const VARIANTS: Record<SubdomainState, "default" | "secondary" | "destructive" | "outline"> = {
  ready: "default",
  dns_missing: "destructive",
  no_inbox: "destructive",
  suspended: "secondary",
  retired: "outline",
  unknown: "outline",
};

interface StatusBadgeProps {
  state: SubdomainState;
}

/** Readiness of a subdomain to receive mail. */
export function StatusBadge({ state }: StatusBadgeProps) {
  return <Badge variant={VARIANTS[state]}>{STATE_LABELS[state]}</Badge>;
}
