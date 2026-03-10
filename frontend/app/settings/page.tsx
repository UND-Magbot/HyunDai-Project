"use client";

import { useState, useEffect, useSyncExternalStore } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { MenuPermissionTab } from "../components/ui/settings/MenuPermissionTab";
import { PasswordChangeTab } from "../components/ui/settings/PasswordChangeTab";
import { DbBackupTab } from "../components/ui/settings/DbBackupTab";
import { LoadingScreen } from "../components/ui/LoadingScreen";
import "./settings.css";

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

const subscribe = () => () => {};
function useUserRole() {
  return useSyncExternalStore(
    subscribe,
    () => localStorage.getItem("user_role"),
    () => null
  );
}

type Tab = "menu-permission" | "password-change" | "db-backup";

export default function SettingsPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);
  const [isLoading, setIsLoading] = useState(true);

  const userRole = useUserRole();
  const isAdmin = userRole === "1";

  const [activeTab, setActiveTab] = useState<Tab>("password-change");

  useEffect(() => {
    if (isAdmin) setActiveTab("menu-permission");
  }, [isAdmin]);

  useEffect(() => {
    const t = setTimeout(() => setIsLoading(false), 3000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <>
      {isLoading && <LoadingScreen pageName="설정" />}
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
            <div className="settings-page">
              <header className="settings-page__header">
                <h1 className="settings-page__title">설정</h1>
                <div className="settings-page__tabs">
                  {isAdmin && (
                    <button
                      className={`settings-page__tab${activeTab === "menu-permission" ? " settings-page__tab--active" : ""}`}
                      onClick={() => setActiveTab("menu-permission")}
                    >
                      메뉴 권한
                    </button>
                  )}
                  {isAdmin && (
                    <button
                      className={`settings-page__tab${activeTab === "db-backup" ? " settings-page__tab--active" : ""}`}
                      onClick={() => setActiveTab("db-backup")}
                    >
                      DB 백업
                    </button>
                  )}
                  <button
                    className={`settings-page__tab${activeTab === "password-change" ? " settings-page__tab--active" : ""}`}
                    onClick={() => setActiveTab("password-change")}
                  >
                    비밀번호 변경
                  </button>
                </div>
              </header>

              {activeTab === "menu-permission" && isAdmin && (
                <MenuPermissionTab />
              )}

              {activeTab === "password-change" && <PasswordChangeTab />}

              {activeTab === "db-backup" && isAdmin && <DbBackupTab />}
            </div>
          </main>
        </div>
      </div>
    </>
  );
}
