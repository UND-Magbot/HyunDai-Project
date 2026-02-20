"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { SettingsRobotTable } from "../components/ui/settings/SettingsRobotTable";
import { OperatedRobotTable } from "../components/ui/settings/OperatedRobotTable";
import { RobotSettingsModal } from "../components/ui/settings/RobotSettingsModal";
import { SettingsDetailModal } from "../components/ui/settings/SettingsDetailModal";
import {
  mockRobotDevices,
  mockBusinesses,
  mockBuildings,
} from "@/lib/mock/robotDevices";
import { CustomTasksTab } from "../components/ui/settings/CustomTasksTab";
import { CruiseRouteTab } from "../components/ui/settings/CruiseRouteTab";
import type { RobotDevice, DeploymentPayload } from "@/lib/types/robots";
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

const PAGE_SIZE = 10;
const PAGE_GROUP = 5;

type Tab = "all" | "operated" | "custom-tasks" | "cruise-route";

export default function SettingsPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);
  const [activeTab, setActiveTab] = useState<Tab>("all");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setIsLoading(false), 3000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  const [devices, setDevices] = useState<RobotDevice[]>(() =>
    mockRobotDevices.map((d) => ({ ...d, currentTask: [...d.currentTask] }))
  );

  // ─── All Robots state ───
  const [allSearch, setAllSearch] = useState("");
  const [allAppliedSearch, setAllAppliedSearch] = useState("");
  const [allPage, setAllPage] = useState(1);
  const [settingsDeviceId, setSettingsDeviceId] = useState<string | null>(null);
  const [detailDeviceId, setDetailDeviceId] = useState<string | null>(null);

  // ─── Operated Robots state ───
  const [opSearch, setOpSearch] = useState("");
  const [opAppliedSearch, setOpAppliedSearch] = useState("");
  const [opPage, setOpPage] = useState(1);

  // ─── All Robots filtering + pagination ───
  const allFiltered = useMemo(() => {
    if (!allAppliedSearch) return devices;
    const keyword = allAppliedSearch.toLowerCase();
    return devices.filter(
      (d) =>
        d.robotName.toLowerCase().includes(keyword) ||
        d.sn.toLowerCase().includes(keyword)
    );
  }, [devices, allAppliedSearch]);

  const allTotalPages = Math.max(1, Math.ceil(allFiltered.length / PAGE_SIZE));
  const allPaged = useMemo(
    () => allFiltered.slice((allPage - 1) * PAGE_SIZE, allPage * PAGE_SIZE),
    [allFiltered, allPage]
  );

  useEffect(() => {
    if (allPage > allTotalPages) setAllPage(allTotalPages);
  }, [allTotalPages, allPage]);

  const allPageGroupStart = Math.floor((allPage - 1) / PAGE_GROUP) * PAGE_GROUP + 1;
  const allPageNumbers = Array.from(
    { length: Math.min(PAGE_GROUP, allTotalPages - allPageGroupStart + 1) },
    (_, i) => allPageGroupStart + i
  );

  const handleAllSearch = useCallback(() => {
    setAllAppliedSearch(allSearch);
    setAllPage(1);
  }, [allSearch]);

  // ─── Operated Robots filtering + pagination ───
  const deployedDevices = useMemo(
    () => devices.filter((d) => d.busiName != null),
    [devices]
  );

  const opFiltered = useMemo(() => {
    if (!opAppliedSearch) return deployedDevices;
    const keyword = opAppliedSearch.toLowerCase();
    return deployedDevices.filter((d) =>
      d.sn.toLowerCase().includes(keyword)
    );
  }, [deployedDevices, opAppliedSearch]);

  const opTotalPages = Math.max(1, Math.ceil(opFiltered.length / PAGE_SIZE));
  const opPaged = useMemo(
    () => opFiltered.slice((opPage - 1) * PAGE_SIZE, opPage * PAGE_SIZE),
    [opFiltered, opPage]
  );

  useEffect(() => {
    if (opPage > opTotalPages) setOpPage(opTotalPages);
  }, [opTotalPages, opPage]);

  const opPageGroupStart = Math.floor((opPage - 1) / PAGE_GROUP) * PAGE_GROUP + 1;
  const opPageNumbers = Array.from(
    { length: Math.min(PAGE_GROUP, opTotalPages - opPageGroupStart + 1) },
    (_, i) => opPageGroupStart + i
  );

  const handleOpSearch = useCallback(() => {
    setOpAppliedSearch(opSearch);
    setOpPage(1);
  }, [opSearch]);

  const handleOpRefresh = useCallback(() => {
    setDevices(
      mockRobotDevices.map((d) => ({ ...d, currentTask: [...d.currentTask] }))
    );
    setOpSearch("");
    setOpAppliedSearch("");
    setOpPage(1);
  }, []);

  // ─── Settings modal save ───
  const handleSettingsSave = useCallback(
    (deviceId: string, data: DeploymentPayload) => {
      const business = mockBusinesses.find((b) => b.id === data.businessId);
      const building = mockBuildings.find((b) => b.id === data.buildingId);
      setDevices((prev) =>
        prev.map((d) =>
          d.id === deviceId
            ? {
                ...d,
                deploymentTime: data.deploymentDate,
                busiName: business?.name ?? d.busiName,
                buildingName: building?.name ?? d.buildingName,
              }
            : d
        )
      );
    },
    []
  );

  const settingsDevice = settingsDeviceId
    ? devices.find((d) => d.id === settingsDeviceId) ?? null
    : null;

  const detailDevice = detailDeviceId
    ? devices.find((d) => d.id === detailDeviceId) ?? null
    : null;

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
            {/* Header */}
            <header className="settings-page__header">
              <h1 className="settings-page__title">설정</h1>
              <div className="settings-page__tabs">
                <button
                  className={`settings-page__tab${activeTab === "all" ? " settings-page__tab--active" : ""}`}
                  onClick={() => setActiveTab("all")}
                >
                  전체 로봇
                </button>
                <button
                  className={`settings-page__tab${activeTab === "operated" ? " settings-page__tab--active" : ""}`}
                  onClick={() => setActiveTab("operated")}
                >
                  운영 로봇
                </button>
                <button
                  className={`settings-page__tab${activeTab === "custom-tasks" ? " settings-page__tab--active" : ""}`}
                  onClick={() => setActiveTab("custom-tasks")}
                >
                  작업 등록
                </button>
                <button
                  className={`settings-page__tab${activeTab === "cruise-route" ? " settings-page__tab--active" : ""}`}
                  onClick={() => setActiveTab("cruise-route")}
                >
                  경로 등록
                </button>
              </div>
            </header>

            {/* ─── All Robots Section ─── */}
            {activeTab === "all" && (
            <section className="settings-section">

              <div className="settings-search">
                <input
                  type="text"
                  className="settings-search__input"
                  placeholder="Please enter robot info to search"
                  value={allSearch}
                  onChange={(e) => setAllSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAllSearch()}
                />
                <button
                  className="settings-search__btn"
                  onClick={handleAllSearch}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </button>
              </div>

              <SettingsRobotTable
                devices={allPaged}
                onSettingsClick={setSettingsDeviceId}
                onDetailClick={setDetailDeviceId}
              />

              {/* Pagination */}
              <div className="pagination">
                <button
                  className="pagination__btn"
                  disabled={allPage <= 1}
                  onClick={() => setAllPage((p) => p - 1)}
                >
                  이전
                </button>
                {allPageNumbers.map((num) => (
                  <button
                    key={num}
                    className={`pagination__num${num === allPage ? " pagination__num--active" : ""}`}
                    onClick={() => setAllPage(num)}
                  >
                    {num}
                  </button>
                ))}
                <button
                  className="pagination__btn"
                  disabled={allPage >= allTotalPages}
                  onClick={() => setAllPage((p) => p + 1)}
                >
                  다음
                </button>
                <span className="pagination__info">
                  총 {allFiltered.length}개
                </span>
              </div>
            </section>
            )}

            {/* ─── Operated Robots Section ─── */}
            {activeTab === "operated" && (
            <section className="settings-section">

              <div className="settings-search">
                <input
                  type="text"
                  className="settings-search__input"
                  placeholder="Please enter the robot SN code to search"
                  value={opSearch}
                  onChange={(e) => setOpSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleOpSearch()}
                />
                <button
                  className="settings-search__btn"
                  onClick={handleOpSearch}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </button>
                <button
                  className="settings-search__refresh-btn"
                  onClick={handleOpRefresh}
                  title="Refresh"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="23 4 23 10 17 10" />
                    <polyline points="1 20 1 14 7 14" />
                    <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
                  </svg>
                </button>
              </div>

              <OperatedRobotTable devices={opPaged} />

              {/* Pagination */}
              <div className="pagination">
                <button
                  className="pagination__btn"
                  disabled={opPage <= 1}
                  onClick={() => setOpPage((p) => p - 1)}
                >
                  Prev
                </button>
                {opPageNumbers.map((num) => (
                  <button
                    key={num}
                    className={`pagination__num${num === opPage ? " pagination__num--active" : ""}`}
                    onClick={() => setOpPage(num)}
                  >
                    {num}
                  </button>
                ))}
                <button
                  className="pagination__btn"
                  disabled={opPage >= opTotalPages}
                  onClick={() => setOpPage((p) => p + 1)}
                >
                  Next
                </button>
                <span className="pagination__info">
                  {opFiltered.length} items
                </span>
              </div>
            </section>
            )}

            {/* ─── Custom Tasks Section ─── */}
            {activeTab === "custom-tasks" && <CustomTasksTab />}

            {/* ─── Cruise Route Section ─── */}
            {activeTab === "cruise-route" && <CruiseRouteTab />}
          </div>

          <RobotSettingsModal
            device={settingsDevice}
            open={!!settingsDeviceId}
            onClose={() => setSettingsDeviceId(null)}
            onSave={handleSettingsSave}
          />

          <SettingsDetailModal
            device={detailDevice}
            open={!!detailDeviceId}
            onClose={() => setDetailDeviceId(null)}
          />
        </main>
      </div>
    </div>
    </>
  );
}
