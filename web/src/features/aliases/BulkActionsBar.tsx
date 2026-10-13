import { Button } from "@/components/ui/button";
import type { BulkAction } from "@/lib/api";

interface BulkActionsBarProps {
  count: number;
  pending: boolean;
  onAction: (action: BulkAction) => void;
  onClear: () => void;
}

/** Shown while rows are selected: activate, deactivate or delete them together. */
export function BulkActionsBar({ count, pending, onAction, onClear }: BulkActionsBarProps) {
  if (count === 0) return null;
  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm"
    >
      <span className="mr-auto font-medium">{count} selected</span>
      <Button size="sm" variant="outline" disabled={pending} onClick={() => onAction("activate")}>
        Activate
      </Button>
      <Button size="sm" variant="outline" disabled={pending} onClick={() => onAction("deactivate")}>
        Deactivate
      </Button>
      <Button size="sm" variant="destructive" disabled={pending} onClick={() => onAction("delete")}>
        Delete
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear
      </Button>
    </div>
  );
}
