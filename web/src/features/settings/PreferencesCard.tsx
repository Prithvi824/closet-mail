import { TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useUpdateSubdomainSettings } from "@/features/subdomains/api";
import type { SettingsUpdate, SubdomainSettings } from "@/lib/api";
import { errorMessage } from "@/lib/http";

interface SettingRowProps {
  id: string;
  label: string;
  hint: ReactNode;
  children: ReactNode;
}

function SettingRow({ id, label, hint, children }: SettingRowProps) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <Label htmlFor={id}>{label}</Label>
        <div className="text-xs text-muted-foreground">{hint}</div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

interface PreferencesCardProps {
  /** Subdomain label (its domain is <label>.closetcompute.online). */
  label: string;
  settings: SubdomainSettings;
}

/** A subdomain's forwarding preferences; each control saves immediately. */
export function PreferencesCard({ label, settings }: PreferencesCardProps) {
  const subdomain = `${label}.closetcompute.online`;
  const update = useUpdateSubdomainSettings(label);

  function save(changes: SettingsUpdate) {
    update.mutate(changes, {
      onSuccess: () => toast.success("Saved"),
      onError: (error) => toast.error(errorMessage(error, "Could not save")),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Forwarding</CardTitle>
        <CardDescription>How forwarded mail looks.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <SettingRow id="banner-position" label="Banner" hint="The note on forwarded mail with block and disable links.">
          <Select
            value={settings.banner_position}
            onValueChange={(value) => save({ banner_position: value as SubdomainSettings["banner_position"] })}
          >
            <SelectTrigger id="banner-position" className="w-full sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="top">Top</SelectItem>
              <SelectItem value="bottom">Bottom</SelectItem>
              <SelectItem value="off">Off</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>
        <SettingRow id="alias-format" label="New alias style" hint="Default style for random aliases.">
          <Select
            value={settings.alias_format}
            onValueChange={(value) => save({ alias_format: value as SubdomainSettings["alias_format"] })}
          >
            <SelectTrigger id="alias-format" className="w-full sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="words">Words</SelectItem>
              <SelectItem value="chars">Characters</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>
        <SettingRow id="strip-trackers" label="Remove trackers" hint="Strip tracking pixels from forwarded HTML mail.">
          <Switch
            id="strip-trackers"
            checked={settings.strip_trackers}
            disabled={update.isPending}
            onCheckedChange={(strip_trackers) => save({ strip_trackers })}
          />
        </SettingRow>
        <SettingRow
          id="catchall"
          label="Subdomain catch-all"
          hint={<>Any address @{subdomain} creates an alias on first use.</>}
        >
          <Switch
            id="catchall"
            checked={settings.subdomain_catchall}
            disabled={update.isPending}
            onCheckedChange={(subdomain_catchall) => save({ subdomain_catchall })}
          />
        </SettingRow>
        {settings.subdomain_catchall ? (
          <Alert>
            <TriangleAlertIcon />
            <AlertDescription>
              Every catch-all address contains the subdomain, so anyone who sees two of them can tell
              they belong to the same person. Use shared-domain aliases where that matters.
            </AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}
