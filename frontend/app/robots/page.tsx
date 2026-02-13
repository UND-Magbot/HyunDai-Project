"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { RobotFilter } from "../components/ui/robots/RobotFilter";
import { RobotTable } from "../components/ui/robots/RobotTable";
import { RobotDeviceInfo } from "../components/ui/robots/RobotDeviceInfo";
import { ConfirmModal } from "../components/ui/robots/ConfirmModal";
import {
  mockRobotDevices,
  getDistinctModels,
} from "@/lib/mock/robotDevices";
import type { RobotFilterState, RobotDevice } from "@/lib/types/robots";
import "./robots.css";

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

const defaultFilters: RobotFilterState = {
  searchText: "",
  model: "",
  runState: "",
  online: "",
  enable: "",
};

function applyFilters(
  devices: RobotDevice[],
  filters: RobotFilterState
): RobotDevice[] {
  return devices.filter((d) => {
    if (filters.searchText) {
      const keyword = filters.searchText.toLowerCase();
      if (
        !d.sn.toLowerCase().includes(keyword) &&
        !d.robotName.toLowerCase().includes(keyword)
      ) {
        return false;
      }
    }
    if (filters.model && d.model !== filters.model) return false;
    if (filters.runState && d.runState !== filters.runState) return false;
    if (filters.online) {
      const isOnline = filters.online === "Online";
      if (d.online !== isOnline) return false;
    }
    if (filters.enable) {
      const isEnabled = filters.enable === "Enable";
      if (d.enable !== isEnabled) return false;
    }
    return true;
  });
}

export default function RobotsPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);
  const [devices, setDevices] = useState<RobotDevice[]>(() =>
    mockRobotDevices.map((d) => ({ ...d, currentTask: [...d.currentTask] }))
  );
  const [filters, setFilters] = useState<RobotFilterState>(defaultFilters);
  const [appliedFilters, setAppliedFilters] = useState<RobotFilterState>(defaultFilters);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [togglingDeviceId, setTogglingDeviceId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    deviceId: string;
  } | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 10;
  const PAGE_GROUP = 5;

  const models = useMemo(() => getDistinctModels(devices), [devices]);

  const displayDevices = useMemo(
    () => applyFilters(devices, appliedFilters),
    [devices, appliedFilters]
  );

  const totalPages = Math.max(1, Math.ceil(displayDevices.length / PAGE_SIZE));
  const pagedDevices = useMemo(
    () => displayDevices.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [displayDevices, currentPage]
  );

  // Reset to page 1 when applied filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [appliedFilters]);

  // Clamp page if data shrinks
  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [totalPages, currentPage]);

  // Page number group (5 unit)
  const pageGroupStart = Math.floor((currentPage - 1) / PAGE_GROUP) * PAGE_GROUP + 1;
  const pageNumbers = Array.from(
    { length: Math.min(PAGE_GROUP, totalPages - pageGroupStart + 1) },
    (_, i) => pageGroupStart + i
  );

  const performToggle = useCallback(
    (deviceId: string) => {
      const device = devices.find((d) => d.id === deviceId);
      if (!device) return;

      const previousValue = device.enable;
      setTogglingDeviceId(deviceId);
      setErrorMessage(null);

      // Optimistic update
      setDevices((prev) =>
        prev.map((d) =>
          d.id === deviceId ? { ...d, enable: !previousValue } : d
        )
      );

      // Mock API call
      setTimeout(() => {
        if (Math.random() < 0.1) {
          setDevices((prev) =>
            prev.map((d) =>
              d.id === deviceId ? { ...d, enable: previousValue } : d
            )
          );
          setErrorMessage(`Failed to update enable state for ${device.robotName}`);
        }
        setTogglingDeviceId(null);
      }, 300);
    },
    [devices]
  );

  const handleEnableToggle = useCallback(
    (deviceId: string) => {
      const device = devices.find((d) => d.id === deviceId);
      if (!device) return;

      if (device.runState !== "IDLE" && device.runState !== null) {
        setConfirmModal({ deviceId });
        return;
      }

      performToggle(deviceId);
    },
    [devices, performToggle]
  );

  const handleConfirm = useCallback(() => {
    if (confirmModal) {
      performToggle(confirmModal.deviceId);
    }
    setConfirmModal(null);
  }, [confirmModal, performToggle]);

  const handleSearch = useCallback(() => {
    setAppliedFilters({ ...filters });
  }, [filters]);

  const selectedDevice = selectedDeviceId
    ? devices.find((d) => d.id === selectedDeviceId) ?? null
    : null;

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
          <div className="robots-page">
            <header className="robots-page__header">
              <h1 className="robots-page__title">로봇 관리</h1>
            </header>

            <RobotFilter
              filters={filters}
              models={models}
              onFilterChange={setFilters}
              onSearch={handleSearch}
            />

            {errorMessage && (
              <div
                style={{
                  padding: "8px 16px",
                  background: "var(--bg-error-subtle)",
                  border: "1px solid var(--color-error)",
                  borderRadius: "var(--radius-control)",
                  color: "var(--color-error)",
                  fontSize: "14px",
                }}
              >
                {errorMessage}
              </div>
            )}

            <RobotTable
              devices={pagedDevices}
              onEnableToggle={handleEnableToggle}
              onInfoClick={setSelectedDeviceId}
              togglingDeviceId={togglingDeviceId}
            />

            <div className="pagination">
              <button
                className="pagination__btn"
                disabled={currentPage <= 1}
                onClick={() => setCurrentPage((p) => p - 1)}
              >
                Prev
              </button>
              {pageNumbers.map((num) => (
                <button
                  key={num}
                  className={`pagination__num${num === currentPage ? " pagination__num--active" : ""}`}
                  onClick={() => setCurrentPage(num)}
                >
                  {num}
                </button>
              ))}
              <button
                className="pagination__btn"
                disabled={currentPage >= totalPages}
                onClick={() => setCurrentPage((p) => p + 1)}
              >
                Next
              </button>
              <span className="pagination__info">
                {displayDevices.length} items
              </span>
            </div>
          </div>

          {selectedDevice && (
            <RobotDeviceInfo
              device={selectedDevice}
              onClose={() => setSelectedDeviceId(null)}
              onEnableToggle={handleEnableToggle}
              togglingDeviceId={togglingDeviceId}
            />
          )}

          <ConfirmModal
            open={!!confirmModal}
            title="Enable Confirmation"
            message={`This device is currently ${confirmModal ? devices.find((d) => d.id === confirmModal.deviceId)?.runState ?? "" : ""}. Are you sure you want to change its enable state?`}
            onConfirm={handleConfirm}
            onCancel={() => setConfirmModal(null)}
          />
        </main>
      </div>
    </div>
  );
}
