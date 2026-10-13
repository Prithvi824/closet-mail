import { Badge } from "@/components/ui/badge";
import { STATE_LABELS } from "@/features/aliases/types";
import type { AliasState } from "@/lib/api";

const VARIANTS: Record<AliasState, "default" | "secondary" | "destructive" | "outline"> = {
  active: "default",
  inactive: "secondary",
  deleted: "destructive",
  forgotten: "outline",
};

interface AliasStateBadgeProps {
  state: AliasState;
}

export function AliasStateBadge({ state }: AliasStateBadgeProps) {
  return <Badge variant={VARIANTS[state]}>{STATE_LABELS[state]}</Badge>;
}
