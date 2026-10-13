import { TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useRecipients } from "@/features/recipients/api";
import { useUpdateSettings } from "@/features/settings/api";
import type { Me, SettingsUpdate } from "@/lib/api";
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
  user: Me;
}

/** Forwarding preferences; each control saves immediately. */
export function PreferencesCard({ user }: PreferencesCardProps) {
  const recipients = useRecipients();
  const update = useUpdateSettings();
  const usable = (recipients.data ?? []).filter((r) => r.verified && !r.disabled);
  const subdomain = `${user.username}.closetcompute.online`;

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
        <CardDescription>How forwarded mail looks and where it goes.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <SettingRow id="default-recipient" label="Default recipient" hint="Used by aliases without their own recipients.">
          <Select
            value={user.default_recipient_id ?? undefined}
            onValueChange={(value) => save({ default_recipient_id: value })}
          >
            <SelectTrigger id="default-recipient" className="w-full sm:w-64">
              <SelectValue placeholder="Choose a recipient" />
            </SelectTrigger>
            <SelectContent>
              {usable.map((recipient) => (
                <SelectItem key={recipient.id} value={recipient.id}>
                  {recipient.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingRow>
        <SettingRow id="banner-position" label="Banner" hint="The note on forwarded mail with block and disable links.">
          <Select
            value={user.banner_position}
            onValueChange={(value) => save({ banner_position: value as Me["banner_position"] })}
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
            value={user.alias_format}
            onValueChange={(value) => save({ alias_format: value as Me["alias_format"] })}
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
            checked={user.strip_trackers}
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
            checked={user.subdomain_catchall}
            disabled={update.isPending}
            onCheckedChange={(subdomain_catchall) => save({ subdomain_catchall })}
          />
        </SettingRow>
        {user.subdomain_catchall ? (
          <Alert>
            <TriangleAlertIcon />
            <AlertDescription>
              Every catch-all address contains your username, so anyone who sees two of them can tell
              they belong to the same person. Use shared-domain aliases where that matters.
            </AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}
