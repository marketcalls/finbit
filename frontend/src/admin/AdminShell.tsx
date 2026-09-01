/**
 * Chrome for the admin console: navigation, session controls and the banner.
 *
 * The route vocabulary lives here rather than in AdminApp so the shell owns
 * both the list and its labels. AdminApp imports the type and the parser from
 * this file, which keeps the nav and the hash in agreement by construction: a
 * fifth screen is one entry in ADMIN_NAV and nothing else.
 *
 * Navigation writes location.hash and lets AdminApp react to hashchange, the
 * same one-way pattern the public shell uses (CONTRACT.md section 11). That is
 * what makes browser back work through the admin screens without a router.
 *
 * The Toaster is mounted here, once. Sonner stacks and announces toasts itself,
 * and a second instance would duplicate every message.
 *
 * The account area is a cluster rather than a menu. There is exactly one admin
 * account and exactly two things to do with it, so hiding both behind a
 * dropdown would add a click and a focus handover to save no space, and the
 * username has to stay visible anyway.
 */

import { useState } from 'react';
import {
  KeyRound,
  LayoutDashboard,
  Flag,
  LogOut,
  Moon,
  Newspaper,
  Sun,
  UserRound,
  Workflow,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { Button } from '../components/ui/button';
import { Toaster } from '../components/ui/sonner';
import { useTheme } from '../lib/useTheme';
import { cn } from '../lib/utils';
import { ChangePasswordDialog } from './components/ChangePasswordDialog';
import { MaintenanceBanner } from './components/maintenance';
import { useAdminAuth } from './useAdminAuth';

/** The four admin screens, which are also the four hash segments. */
export type AdminRoute = 'dashboard' | 'pipeline' | 'content' | 'flags';

export interface AdminNavItem {
  key: AdminRoute;
  label: string;
  icon: LucideIcon;
  /** One line for the dashboard's quick links. */
  blurb: string;
}

export const ADMIN_NAV: readonly AdminNavItem[] = [
  {
    key: 'dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    blurb: 'Health, article count and the state of the last ingest run.',
  },
  {
    key: 'pipeline',
    label: 'Pipeline',
    icon: Workflow,
    blurb: 'Schedule, the discovery query set and the manual fetch controls.',
  },
  {
    key: 'content',
    label: 'Content',
    icon: Newspaper,
    blurb: 'Search, hide, pin, edit and delete published stories.',
  },
  {
    key: 'flags',
    label: 'Flags',
    icon: Flag,
    blurb: 'Categories, market filters, default sort and maintenance mode.',
  },
];

const ADMIN_ROUTES: readonly AdminRoute[] = ADMIN_NAV.map((item) => item.key);

/** The default screen, and what an unknown admin sub-path falls back to. */
export const DEFAULT_ADMIN_ROUTE: AdminRoute = 'dashboard';

export function isAdminRoute(value: string): value is AdminRoute {
  return (ADMIN_ROUTES as readonly string[]).includes(value);
}

/** The hash that addresses one admin screen, for example '#/admin/pipeline'. */
export function adminRouteHash(route: AdminRoute): string {
  return route === DEFAULT_ADMIN_ROUTE ? '#/admin' : `#/admin/${route}`;
}

export interface AdminShellProps {
  route: AdminRoute;
  onNavigate: (route: AdminRoute) => void;
  children: ReactNode;
}

export function AdminShell({ route, onNavigate, children }: AdminShellProps): JSX.Element {
  const { username, logout } = useAdminAuth();
  const { theme, toggleTheme } = useTheme();
  const [changingPassword, setChangingPassword] = useState(false);

  return (
    <div className="min-h-dvh bg-bg text-fg">
      {/* Sticky so the warning stays on screen while a long table scrolls. */}
      <div className="sticky top-0 z-40">
        <MaintenanceBanner />
      </div>

      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <a
            href="#/feed"
            className="font-headline text-lg font-semibold text-fg"
            title="Back to the public feed"
          >
            FinBit
          </a>
          <span className="rounded-md border border-border px-2 py-0.5 text-xs font-medium text-muted-fg">
            Admin
          </span>

          <div className="ml-auto flex items-center gap-2">
            {/*
              The username is always on screen, even on a phone: knowing whose
              audit_log rows a destructive action will carry is not optional.
              Only the surrounding sentence collapses on a narrow viewport.
            */}
            <div className="flex items-center gap-1 rounded-md border border-border py-0.5 pl-2">
              <UserRound aria-hidden="true" className="size-4 shrink-0 text-muted-fg" />
              <span className="max-w-40 truncate text-sm text-muted-fg">
                <span className="hidden sm:inline">Signed in as </span>
                <span className="font-medium text-fg">{username ?? 'unknown'}</span>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Change password"
                title="Change password"
                onClick={() => {
                  setChangingPassword(true);
                }}
              >
                <KeyRound aria-hidden="true" />
              </Button>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme'}
              onClick={toggleTheme}
            >
              {theme === 'dark' ? (
                <Sun aria-hidden="true" />
              ) : (
                <Moon aria-hidden="true" />
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void logout();
              }}
            >
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:flex-row">
        {/*
          A sidebar on desktop, a horizontally scrollable row on a phone. Both
          are the same list of links, so the current screen is marked with
          aria-current in either layout rather than by colour alone.
        */}
        <nav
          aria-label="Admin sections"
          className="-mx-4 flex shrink-0 gap-1 overflow-x-auto px-4 md:mx-0 md:w-56 md:flex-col md:overflow-visible md:px-0"
        >
          {ADMIN_NAV.map((item) => {
            const Icon = item.icon;
            const active = item.key === route;
            return (
              <a
                key={item.key}
                href={adminRouteHash(item.key)}
                aria-current={active ? 'page' : undefined}
                onClick={(event) => {
                  // Let a modified click open a new tab, handle a plain one here.
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
                    return;
                  }
                  event.preventDefault();
                  onNavigate(item.key);
                }}
                className={cn(
                  'flex min-h-11 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors duration-150',
                  active
                    ? 'bg-muted text-fg'
                    : 'text-muted-fg hover:bg-muted hover:text-fg',
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
                {item.label}
              </a>
            );
          })}
        </nav>

        <main className="min-w-0 flex-1">{children}</main>
      </div>

      <ChangePasswordDialog open={changingPassword} onOpenChange={setChangingPassword} />

      <Toaster />
    </div>
  );
}
