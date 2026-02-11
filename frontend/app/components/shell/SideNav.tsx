"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { NavItem, SideNavProps } from "@/lib/types/shell";

export const defaultNavItems: NavItem[] = [
  { label: "monitoring", href: "/monitoring", match: "/monitoring", icon: "M" },
  { label: "robots", href: "/robots", match: "/robots", icon: "R" },
  { label: "tasks", href: "/tasks", match: "/tasks", icon: "T" },
  { label: "logs", href: "/logs", match: "/logs", icon: "L" },
  { label: "map", href: "/map", match: "/map", icon: "P" },
  { label: "settings", href: "/settings", match: "/settings", icon: "S" },
];

export function SideNav({
  items,
  collapsed = false,
  onClose,
  onItemSelect,
}: SideNavProps) {
  const pathname = usePathname();
  const classes = [
    "side-nav",
    collapsed ? "side-nav--collapsed" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      {!collapsed ? (
        <button
          className="side-nav__backdrop"
          aria-label="Close navigation"
          onClick={onClose}
        />
      ) : null}
      <nav className={classes} aria-label="Primary">
        <ul className="side-nav__list">
          {items.map((item) => {
            const isActive = item.match
              ? pathname.startsWith(item.match)
              : pathname === item.href;

            return (
              <li
                key={item.label}
                className={
                  isActive
                    ? "side-nav__item side-nav__item--active"
                    : "side-nav__item"
                }
              >
                <Link
                  href={item.href}
                  className="side-nav__link"
                  aria-label={item.label}
                  title={collapsed ? item.label : undefined}
                  onClick={onItemSelect}
                >
                  <span className="side-nav__icon" aria-hidden="true">
                    {item.icon}
                  </span>
                  <span className="side-nav__label">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}
