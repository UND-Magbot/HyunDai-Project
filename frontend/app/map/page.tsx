"use client";

import { useEffect, useState } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { UnderDevelopment } from "../components/ui/UnderDevelopment";

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

export default function MapPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="app-shell">
      <TopBar
        dateTime={currentDateTime}
        onToggleNav={() => setNavCollapsed((v) => !v)}
        navExpanded={!navCollapsed}
      />
      <div className="shell-body">
        <SideNav
          items={defaultNavItems}
          collapsed={navCollapsed}
          onClose={() => setNavCollapsed(true)}
          onItemSelect={() => setNavCollapsed(true)}
        />
        <main className="main-content">
          <UnderDevelopment pageName="Map" />
        </main>
      </div>
    </div>
  );
}
