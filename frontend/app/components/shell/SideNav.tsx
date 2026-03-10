"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { NavItem, SideNavProps } from "@/lib/types/shell";

export const defaultNavItems: NavItem[] = [
  { label: "모니터링", href: "/monitoring", match: "/monitoring", icon: "/icon/Icon (9).png" },
  { label: "로봇관리", href: "/robots", match: "/robots", icon: "/icon/Icon (13).png" },
  // { label: "tasks", href: "/tasks", match: "/tasks", icon: "/icon/Icon (15).png" },
  { label: "로그관리", href: "/logs", match: "/logs", icon: "/icon/zoom-in-w.png" },
  { label: "맵관리", href: "/map", match: "/map", icon: "/icon/Icon (24).png" },
  { label: "설정", href: "/settings", match: "/settings", icon: "/icon/Icon (17).png" },
];

export function SideNav({
  items,
  collapsed = false,
  onClose,
  onItemSelect,
}: SideNavProps) {
  const pathname = usePathname();
  const [allowedLabels, setAllowedLabels] = useState<Set<string> | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("allowed_menus");
    if (stored) {
      setAllowedLabels(new Set(JSON.parse(stored) as string[]));
    }
  }, []);

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
          {items
            .filter((item) => !allowedLabels || allowedLabels.has(item.label))
            .map((item) => {
            const isActive = item.match
              ? pathname.startsWith(item.match)
              : pathname === item.href;

            const itemClass = [
              "side-nav__item",
              isActive ? "side-nav__item--active" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <li key={item.label} className={itemClass}>
                <Link
                  href={item.href}
                  className="side-nav__link"
                  aria-label={item.label}
                  title={collapsed ? item.label : undefined}
                  onClick={onItemSelect}
                >
                  <span className="side-nav__icon" aria-hidden="true">
                    <img src={item.icon} alt="" width={24} height={24} />
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
