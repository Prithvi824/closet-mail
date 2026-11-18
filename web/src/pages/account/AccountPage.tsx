import { PageHeader } from "@/components/PageHeader";
import { useSession } from "@/features/auth/useSession";
import { PasskeysCard } from "@/features/settings/PasskeysCard";
import { TwoFactorCard } from "@/features/settings/TwoFactorCard";

/** The operator's own sign-in security: TOTP and passkeys. */
export function AccountPage() {
  const { user } = useSession();
  if (!user) return null;
  return (
    <>
      <PageHeader title="Account" description="How you sign in to the operator console." />
      <div className="flex flex-col gap-6">
        <TwoFactorCard user={user} />
        <PasskeysCard />
      </div>
    </>
  );
}
