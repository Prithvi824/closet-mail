import { MenuIcon } from "lucide-react";
import { useState } from "react";
import { Link, Outlet } from "react-router";

import { Sidebar } from "@/app/Sidebar";
import { UserMenu } from "@/app/UserMenu";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useSession } from "@/features/auth/useSession";

/** Signed-in shell: sidebar (sheet on small screens), header and the page outlet. */
export function AppLayout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, isAdmin } = useSession();

  return (
    <div className="flex min-h-svh">
      <aside className="hidden w-60 shrink-0 border-r bg-sidebar md:block">
        <Link to="/aliases" className="flex h-14 items-center border-b px-6 text-sm font-semibold">
          closetcompute
        </Link>
        <Sidebar isAdmin={isAdmin} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-2 border-b px-4">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                <MenuIcon />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-0">
              <SheetTitle className="flex h-14 items-center border-b px-6 text-sm">closetcompute</SheetTitle>
              <Sidebar isAdmin={isAdmin} onNavigate={() => setMenuOpen(false)} />
            </SheetContent>
          </Sheet>
          <div className="flex-1" />
          <ThemeToggle />
          {user ? <UserMenu user={user} /> : null}
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
