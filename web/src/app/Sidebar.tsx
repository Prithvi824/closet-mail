import { NavLink } from "react-router";

import { ADMIN_NAV, MAIN_NAV, type NavItem } from "@/app/navigation";
import { cn } from "@/lib/utils";

interface SidebarProps {
  isAdmin: boolean;
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

/** App navigation; the admin section only renders for admins. */
export function Sidebar({ isAdmin, onNavigate }: SidebarProps) {
  return (
    <nav aria-label="Main" className="flex flex-col p-3">
      <NavSection items={MAIN_NAV} onNavigate={onNavigate} />
      {isAdmin ? <NavSection title="Admin" items={ADMIN_NAV} onNavigate={onNavigate} /> : null}
    </nav>
  );
}
