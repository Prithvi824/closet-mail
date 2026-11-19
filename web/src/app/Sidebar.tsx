import { NavLink, useMatch } from "react-router";

import { OPERATOR_NAV, SUBDOMAIN_NAV, type NavItem } from "@/app/navigation";
import { SubdomainSwitcher } from "@/features/subdomains/SubdomainSwitcher";
import { subdomainPage } from "@/lib/paths";
import { cn } from "@/lib/utils";

interface SidebarProps {
  /** The operator's own label, used when no subdomain is open. */
  operatorLabel: string;
  /** Called after a link is chosen (closes the mobile sheet). */
  onNavigate?: () => void;
}

interface NavSectionProps {
  title?: string;
  items: NavItem[];
  onNavigate?: () => void;
}

function NavSection({ title, items, onNavigate }: NavSectionProps) {
  return (
    <div className="flex flex-col gap-1">
      {title ? (
        <p className="px-3 pt-4 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {title}
        </p>
      ) : null}
      {items.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              isActive
                ? "bg-accent font-medium text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )
          }
        >
          <Icon className="size-4" aria-hidden />
          {label}
        </NavLink>
      ))}
    </div>
  );
}

/** Operator pages, then the subdomain switcher and the open subdomain's sections. */
export function Sidebar({ operatorLabel, onNavigate }: SidebarProps) {
  const label = useMatch("/s/:label/*")?.params.label ?? operatorLabel;
  const scoped = SUBDOMAIN_NAV.map((item) => ({ ...item, to: subdomainPage(label, item.to) }));

  return (
    <nav aria-label="Main" className="flex flex-col p-3">
      <NavSection items={OPERATOR_NAV} onNavigate={onNavigate} />
      <SubdomainSwitcher label={label} onNavigate={onNavigate} />
      <NavSection items={scoped} onNavigate={onNavigate} />
    </nav>
  );
}
