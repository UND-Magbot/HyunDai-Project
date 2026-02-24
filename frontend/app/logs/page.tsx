"use client";

import { useState, useMemo, useEffect } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { LogFilter } from "../components/ui/logs/LogFilter";
import { LogTable } from "../components/ui/logs/LogTable";
import { mockLogList, getDistinctRobotSNs } from "@/lib/mock/logList";
import type { LogFilterState, LogItem } from "@/lib/types/logs";
import { LoadingScreen } from "../components/ui/LoadingScreen";
import "./logs.css";

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

const defaultFilters: LogFilterState = {
  message: "",
  robotSn: "",
  logType: "",
  logTag: "",
  date: null,
  startTime: "00:00",
  endTime: "23:59",
};

function applyFilters(
  logs: LogItem[],
  filters: LogFilterState
): LogItem[] {
  return logs.filter((log) => {
    if (filters.message) {
      const keyword = filters.message.toLowerCase();
      if (!log.message.toLowerCase().includes(keyword)) return false;
    }
    if (filters.logType && log.type !== filters.logType) return false;
    if (filters.logTag && log.tag !== filters.logTag) return false;
    if (filters.date) {
      const logDate = log.time.split(" ")[0];
      if (logDate !== filters.date) return false;
    }
    if (filters.startTime && filters.endTime) {
      const logTime = log.time.split(" ")[1]?.substring(0, 5) ?? "";
      if (logTime < filters.startTime || logTime > filters.endTime) return false;
    }
    return true;
  });
}

const PAGE_SIZE = 10;
const PAGE_GROUP = 5;

export default function LogsPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setIsLoading(false), 3000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  const [filters, setFilters] = useState<LogFilterState>(defaultFilters);
  const [appliedFilters, setAppliedFilters] = useState<LogFilterState>(defaultFilters);
  const [currentPage, setCurrentPage] = useState(1);

  const robotSns = useMemo(() => getDistinctRobotSNs(), []);

  const displayLogs = useMemo(
    () => applyFilters(mockLogList, appliedFilters),
    [appliedFilters]
  );

  const totalPages = Math.max(1, Math.ceil(displayLogs.length / PAGE_SIZE));
  const pagedLogs = useMemo(
    () => displayLogs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [displayLogs, currentPage]
  );

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

  const handleSearch = () => {
    setAppliedFilters({ ...filters });
    setCurrentPage(1);
  };

  return (
    <>
      {isLoading && <LoadingScreen pageName="로그 관리" />}
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
          <div className="logs-page">
            <header className="logs-page__header">
              <h1 className="logs-page__title">로그 관리</h1>
            </header>

            <LogFilter
              filters={filters}
              robotSns={robotSns}
              onFilterChange={setFilters}
              onSearch={handleSearch}
            />

            <LogTable logs={pagedLogs} />

            <div className="pagination">
              <button
                className="pagination__btn"
                disabled={currentPage <= 1}
                onClick={() => setCurrentPage((p) => p - 1)}
              >
                이전
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
                다음
              </button>
              <span className="pagination__info">
                총 {displayLogs.length}개
              </span>
            </div>
          </div>
        </main>
      </div>
    </div>
    </>
  );
}
