"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  BookOpen,
  ChevronRight,
  Inbox,
  LogOut,
  Package,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { readJson } from "@/lib/http";
import type { Session } from "@/lib/domain";
import { Brand, Notice } from "./ui";

type Page = "inbox" | "orders" | "operations" | "settings";
const crumbs: Record<Page, string> = {
  inbox: "Resolution cases",
  orders: "Orders",
  operations: "Operations",
  settings: "Settings",
};

/** The merchant workspace frame (sidebar, top bar, breadcrumb, mobile nav) for pages outside the case inbox. */
export function WorkspaceShell({
  active,
  merchant,
  contentId,
  children,
}: {
  active: Page;
  merchant?: Pick<NonNullable<Session["merchant"]>, "name"> | null;
  contentId: string;
  children: ReactNode;
}) {
  const [error, setError] = useState("");
  async function signOut() {
    try {
      await readJson<Session>(
        await fetch("/api/session", { method: "DELETE" }),
      );
      window.location.assign("/login");
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not sign out. Try again.",
      );
    }
  }
  const rail = (
    page: Page,
    href: string,
    label: string,
    Icon: typeof Inbox,
  ) => (
    <Link
      href={href}
      className={`rail-link ${active === page ? "rail-active" : ""}`}
      aria-current={active === page ? "page" : undefined}
    >
      <Icon size={18} />
      <span>{label}</span>
      <ChevronRight className="rail-chevron" size={15} />
    </Link>
  );
  const initials = (merchant?.name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  return (
    <div className="app-shell">
      <a className="skip-link" href={"#" + contentId}>
        Skip to {crumbs[active].toLowerCase()}
      </a>
      <aside className="sidebar" aria-label="Workspace navigation">
        <div className="sidebar-brand">
          <Link href="/" aria-label="Resolve home">
            <Brand />
          </Link>
          <span>MERCHANT WORKSPACE</span>
        </div>
        <div className="sidebar-group">
          <div className="sidebar-label">WORKSPACE</div>
          {rail("inbox", "/workspace", "Case inbox", Inbox)}
          {rail("orders", "/workspace/orders", "Orders", Package)}
          {rail("operations", "/workspace/operations", "Operations", Activity)}
          {rail("settings", "/workspace/settings", "Settings", Settings2)}
        </div>
        <div className="sidebar-bottom">
          <Link href="/docs" className="rail-link">
            <BookOpen size={17} />
            <span>Documentation</span>
          </Link>
          <div className="sidebar-mode">
            <span className="sidebar-mode-icon">
              <ShieldCheck size={19} />
            </span>
            <div>
              <strong>Merchant session</strong>
              <p>Signed in to your workspace.</p>
            </div>
          </div>
          <Link href="/workspace" className="rail-link">
            <BookOpen size={17} />
            <span>Back to cases</span>
          </Link>
        </div>
      </aside>
      <main id={contentId} className="main-pane">
        <header className="topbar">
          <nav className="topbar-crumb" aria-label="Breadcrumb">
            <Link href="/workspace">Workspace</Link>
            <ChevronRight size={14} />
            <strong aria-current="page">{crumbs[active]}</strong>
          </nav>
          <div className="mobile-brand">
            <Brand small />
          </div>
          <div className="topbar-actions">
            <span className="mode-chip">
              <span />
              Signed in
            </span>
            <Link
              href="/workspace/operations"
              className={`button button-secondary connect-button ${active === "operations" ? "topbar-current" : ""}`}
              aria-label="Operations"
              title="Operations"
              aria-current={active === "operations" ? "page" : undefined}
            >
              <Activity size={16} />
              <span>Operations</span>
            </Link>
            <Link
              href="/workspace/settings"
              className={`button button-secondary connect-button ${active === "settings" ? "topbar-current" : ""}`}
              aria-label="Account settings"
              title="Account settings"
              aria-current={active === "settings" ? "page" : undefined}
            >
              <Settings2 size={16} />
              <span>Settings</span>
            </Link>
            <button
              type="button"
              onClick={() => void signOut()}
              className="button button-secondary connect-button"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={16} />
              <span>Sign out</span>
            </button>
            {initials && (
              <span className="avatar" aria-label={merchant?.name}>
                {initials}
              </span>
            )}
          </div>
        </header>
        <nav className="mobile-nav" aria-label="Mobile navigation">
          <Link href="/workspace" className="button button-ghost">
            <Inbox size={16} /> Inbox
          </Link>
          <Link
            href="/workspace/orders"
            className={`button ${active === "orders" ? "button-primary" : "button-ghost"}`}
          >
            <Package size={16} /> Orders
          </Link>
          <Link
            href="/workspace/operations"
            className={`button ${active === "operations" ? "button-primary" : "button-ghost"}`}
          >
            <Activity size={16} /> Operations
          </Link>
          <Link
            href="/workspace/settings"
            className={`button ${active === "settings" ? "button-primary" : "button-ghost"}`}
          >
            <Settings2 size={16} /> Settings
          </Link>
        </nav>
        <div className="workspace">
          {error && <Notice>{error}</Notice>}
          {children}
        </div>
      </main>
    </div>
  );
}
