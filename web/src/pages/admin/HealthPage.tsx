import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { useHealth } from "@/features/admin/api";
import { DlqPanel } from "@/features/admin/DlqPanel";
import { backlogStatus, formatAge, heartbeatStatus, sendStatus } from "@/features/admin/health";
import { HealthTile } from "@/features/admin/HealthTile";
import { formatRelative } from "@/lib/format";
import { errorMessage } from "@/lib/http";

const UNKNOWN = "—";

export function HealthPage() {
  const health = useHealth();
  const data = health.data;
  const reconcile = data?.kv_reconcile as { at?: string; missing?: number; extra?: number } | null | undefined;

  return (
    <>
      <PageHeader title="Health" description="Refreshes every 30 seconds." />
      {health.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {health.isError ? <p className="text-sm text-destructive">{errorMessage(health.error)}</p> : null}
      {data ? (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <HealthTile
              label="Mail processor"
              status={heartbeatStatus(data)}
              value={data.heartbeat_age_seconds == null ? "Down" : `${formatAge(data.heartbeat_age_seconds)} ago`}
              hint="Last heartbeat"
            />
            <HealthTile
              label="Inbound backlog"
              status={backlogStatus(data.inbound_backlog, false)}
              value={data.inbound_backlog ?? UNKNOWN}
              hint="Waiting in the Cloudflare queue"
            />
            <HealthTile
              label="Dead letters"
              status={backlogStatus(data.dlq_backlog, true)}
              value={data.dlq_backlog ?? UNKNOWN}
              hint="Failed after 5 tries"
            />
            <HealthTile
              label="Sent today"
              status={sendStatus(data)}
              value={`${data.sends_today} / ${data.send_cap}`}
              hint="Relay daily cap (UTC)"
            />
            <HealthTile
              label="Bounces · complaints"
              status={data.complaints_7d > 0 ? "warn" : data.hard_bounces_7d > 0 ? "warn" : "ok"}
              value={`${data.hard_bounces_7d} · ${data.complaints_7d}`}
              hint="Last 7 days"
            />
            <HealthTile
              label="KV sync"
              status={!reconcile ? "unknown" : reconcile.missing ? "warn" : "ok"}
              value={reconcile?.at ? formatRelative(reconcile.at) : "Never"}
              hint={reconcile ? `${reconcile.missing ?? 0} missing · ${reconcile.extra ?? 0} extra keys` : "Edge routing table"}
            />
          </div>
          <DlqPanel />
        </div>
      ) : null}
    </>
  );
}
