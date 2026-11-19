import { useMatch, useNavigate } from "react-router";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useSubdomains } from "@/features/subdomains/api";
import { subdomainPage } from "@/lib/paths";

interface SubdomainSwitcherProps {
  /** The selected subdomain label. */
  label: string;
  /** Called after switching (closes the mobile sheet). */
  onNavigate?: () => void;
}

/** Picks the subdomain to work in, staying on the same section (aliases, inboxes, ...). */
export function SubdomainSwitcher({ label, onNavigate }: SubdomainSwitcherProps) {
  const subdomains = useSubdomains();
  const navigate = useNavigate();
  const section = useMatch("/s/:label/:section")?.params.section ?? "aliases";
  const known = (subdomains.data ?? []).some((item) => item.label === label);

  function choose(next: string) {
    void navigate(subdomainPage(next, section));
    onNavigate?.();
  }

  return (
    <div className="flex flex-col gap-1.5 px-3 pt-4">
      <Label htmlFor="subdomain-switcher" className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Subdomain
      </Label>
      <Select value={label} onValueChange={choose}>
        <SelectTrigger id="subdomain-switcher" className="w-full">
          <SelectValue placeholder="Choose a subdomain" />
        </SelectTrigger>
        <SelectContent>
          {known ? null : <SelectItem value={label}>{label}</SelectItem>}
          {(subdomains.data ?? []).map((item) => (
            <SelectItem key={item.id} value={item.label}>
              {item.label}
              {item.retired ? " (retired)" : item.suspended ? " (suspended)" : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
