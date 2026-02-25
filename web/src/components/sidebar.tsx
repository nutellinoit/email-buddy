"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  LayoutDashboard,
  Mail,
  Brain,
  FileText,
  Settings,
  PanelLeftClose,
  PanelLeft,
  Menu,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/emails", label: "Emails", icon: Mail },
  { href: "/learning", label: "Learning", icon: Brain },
  { href: "/summaries", label: "Summaries", icon: FileText },
  { href: "/status", label: "Status", icon: Settings },
];

const STORAGE_KEY = "sidebar-collapsed";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "true") setCollapsed(true);
  }, []);

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem(STORAGE_KEY, String(next));
  };

  const closeMobile = () => setMobileOpen(false);

  return (
    <>
      {/* Mobile header bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 flex items-center gap-3 border-b border-border bg-card px-4 h-12">
        <Button
          variant="ghost"
          size="icon"
          className="shrink-0"
          onClick={() => setMobileOpen(true)}
        >
          <Menu className="h-5 w-5" />
        </Button>
        <span className="text-sm font-semibold">Email-Buddy</span>
      </div>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/50"
          onClick={closeMobile}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          // Base
          "flex flex-col border-r border-border bg-card transition-all duration-200",
          // Desktop
          "hidden md:flex shrink-0",
          collapsed ? "w-14" : "w-56",
          // Mobile overlay
          mobileOpen &&
            "!fixed inset-y-0 left-0 z-50 !flex w-56 shadow-xl"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between h-12 px-3 border-b border-border">
          {collapsed ? (
            <Button
              variant="ghost"
              size="icon"
              className="hidden md:flex mx-auto shrink-0"
              onClick={toggleCollapsed}
            >
              <PanelLeft className="h-4 w-4" />
            </Button>
          ) : (
            <>
              <span className="text-sm font-semibold truncate">Email-Buddy</span>
              <Button
                variant="ghost"
                size="icon"
                className="hidden md:flex shrink-0"
                onClick={toggleCollapsed}
              >
                <PanelLeftClose className="h-4 w-4" />
              </Button>
            </>
          )}
          {/* Mobile close */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden ml-auto shrink-0"
            onClick={closeMobile}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Nav */}
        <nav className="flex-1 flex flex-col gap-1 p-2">
          {navItems.map((item) => {
            const active = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={closeMobile}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                )}
                title={collapsed ? item.label : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

      </aside>
    </>
  );
}
