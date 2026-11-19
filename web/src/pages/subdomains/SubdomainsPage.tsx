import { GlobeIcon, PlusIcon } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSubdomains } from "@/features/subdomains/api";
import { CreateSubdomainDialog } from "@/features/subdomains/CreateSubdomainDialog";
import { SubdomainSheet } from "@/features/subdomains/SubdomainSheet";
import { SubdomainTable } from "@/features/subdomains/SubdomainTable";
import { errorMessage } from "@/lib/http";

/** The subdomains the operator runs, with status, today's numbers and management. */
export function SubdomainsPage() {
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState<string | null>(null);
  const subdomains = useSubdomains();
  const selected = subdomains.data?.find((item) => item.label === managing) ?? null;

  return (
    <>
      <PageHeader
        title="Subdomains"
        description="Each person you serve has a subdomain. Its Cloudflare Email Routing entry is added by hand."
        actions={
          <Button onClick={() => setCreating(true)}>
            <PlusIcon /> New subdomain
          </Button>
        }
      />
      {subdomains.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {subdomains.isError ? (
        <p className="text-sm text-destructive">{errorMessage(subdomains.error, "Could not load subdomains")}</p>
      ) : null}
      {subdomains.data?.length === 0 ? <EmptyState icon={GlobeIcon} title="No subdomains yet" /> : null}
      {subdomains.data?.length ? <SubdomainTable subdomains={subdomains.data} onManage={setManaging} /> : null}
      <CreateSubdomainDialog open={creating} onOpenChange={setCreating} />
      <SubdomainSheet subdomain={selected} onClose={() => setManaging(null)} />
    </>
  );
}
