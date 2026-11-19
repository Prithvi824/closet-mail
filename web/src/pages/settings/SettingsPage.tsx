import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { PreferencesCard } from "@/features/settings/PreferencesCard";
import { useSubdomainSettings } from "@/features/subdomains/api";
import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import { errorMessage } from "@/lib/http";

/** Forwarding preferences of the current subdomain. */
export function SettingsPage() {
  const label = useSubdomainLabel();
  const settings = useSubdomainSettings(label);

  return (
    <>
      <PageHeader title="Settings" description={`Forwarding preferences for ${label}.closetcompute.online.`} />
      {settings.isPending ? <Skeleton className="h-48 w-full" /> : null}
      {settings.isError ? (
        <p className="text-sm text-destructive">{errorMessage(settings.error, "Could not load settings")}</p>
      ) : null}
      {settings.data ? <PreferencesCard key={label} label={label} settings={settings.data} /> : null}
    </>
  );
}
