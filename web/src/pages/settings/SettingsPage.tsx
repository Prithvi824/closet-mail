import { PageHeader } from "@/components/PageHeader";
import { useSession } from "@/features/auth/useSession";
import { PasskeysCard } from "@/features/settings/PasskeysCard";
import { PreferencesCard } from "@/features/settings/PreferencesCard";
import { TwoFactorCard } from "@/features/settings/TwoFactorCard";

export function SettingsPage() {
  const { user } = useSession();
  if (!user) return null;
  return (
    <>
      <PageHeader title="Settings" />
      <div className="flex flex-col gap-6">
        <PreferencesCard user={user} />
        <TwoFactorCard user={user} />
        <PasskeysCard />
      </div>
    </>
  );
}
