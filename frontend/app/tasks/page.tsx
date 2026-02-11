"use client";

import { useState } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { UnderDevelopment } from "../components/ui/UnderDevelopment";

export default function TasksPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);

  return (
    <div className="app-shell">
      <TopBar
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
          <UnderDevelopment pageName="Tasks" />
        </main>
      </div>
    </div>
  );
}
