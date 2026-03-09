"use client";

import { useState, useEffect, useCallback } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { LogFilter } from "../components/ui/logs/LogFilter";
import { LogTable } from "../components/ui/logs/LogTable";
import type { LogFilterState, LogItem } from "@/lib/types/logs";
import { LoadingScreen } from "../components/ui/LoadingScreen";
import { apiFetch } from "@/lib/api";
import * as XLSX from "xlsx";
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

function formatCreatedAt(raw: string): string {
  const d = new Date(raw);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

type ActivityLogItem = {
  id: number;
  category: string;
  category_name: string;
  action: string;
  message: string;
  detail: string | null;
  robot_id: number | null;
  robot_name: string | null;
  source: string | null;
  created_at: string;
};

const CATEGORY_TO_API: Record<string, string> = {
  "시스템": "system",
  "로봇": "robot",
};

function toErrorType(category: string): LogItem["errorType"] {
  if (category === "system") return "시스템";
  if (category === "robot") return "로봇";
  return "사용자";
}

function toLogItem(item: ActivityLogItem): LogItem {
  return {
    id: String(item.id),
    time: formatCreatedAt(item.created_at),
    errorType: toErrorType(item.category),
    ip: item.robot_name ?? item.source ?? "-",
    message: item.message,
    data: item.detail ?? null,
  };
}

const defaultFilters: LogFilterState = {
  message: "",
  errorType: "",
  date: null,
  startTime: "00:00",
  endTime: "23:59",
};

const PAGE_SIZE = 8;
const PAGE_GROUP = 5;

function buildParams(f: LogFilterState, skip: number, limit: number): string {
  const p = new URLSearchParams();
  p.set("skip", String(skip));
  p.set("limit", String(limit));
  if (f.message) p.set("message", f.message);
  const cat = f.errorType ? CATEGORY_TO_API[f.errorType] : undefined;
  if (cat) p.set("category", cat);
  if (f.date) {
    p.set("date_from", `${f.date}T${f.startTime}:00`);
    p.set("date_to", `${f.date}T${f.endTime}:59`);
  }
  return p.toString();
}

export default function LogsPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);
  const [isLoading, setIsLoading] = useState(true);

  const [logs, setLogs] = useState<LogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<LogFilterState>(defaultFilters);
  const [appliedFilters, setAppliedFilters] = useState<LogFilterState>(defaultFilters);
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  const fetchLogs = useCallback(async (f: LogFilterState, page: number) => {
    setIsLoading(true);
    try {
      const qs = buildParams(f, (page - 1) * PAGE_SIZE, PAGE_SIZE);
      const res = await apiFetch<{ total: number; items: ActivityLogItem[] }>(
        `/api/activity-logs?${qs}`
      );
      setTotal(res.total);
      setLogs(res.items.map(toLogItem));
    } catch {
      setLogs([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLogs(appliedFilters, currentPage);
  }, [appliedFilters, currentPage, fetchLogs]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Clamp page if total shrinks
  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [totalPages, currentPage]);

  const pageGroupStart =
    Math.floor((currentPage - 1) / PAGE_GROUP) * PAGE_GROUP + 1;
  const pageNumbers = Array.from(
    { length: Math.min(PAGE_GROUP, totalPages - pageGroupStart + 1) },
    (_, i) => pageGroupStart + i
  );

  const handleSearch = () => {
    setAppliedFilters({ ...filters });
    setCurrentPage(1);
  };

  const handleReset = () => {
    setFilters(defaultFilters);
    setAppliedFilters(defaultFilters);
    setCurrentPage(1);
  };

  const handleExport = async () => {
    try {
      const qs = buildParams(appliedFilters, 0, 500);
      const res = await apiFetch<{ total: number; items: ActivityLogItem[] }>(
        `/api/activity-logs?${qs}`
      );
      const rows = res.items.map((item) => ({
        "발생 일시": formatCreatedAt(item.created_at),
        "오류 타입": toErrorType(item.category),
        IP: item.robot_name ?? item.source ?? "-",
        "메세지": item.message,
        "데이터": item.detail ?? "",
      }));
      const ws = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "로그");
      XLSX.writeFile(wb, `logs_${new Date().toISOString().slice(0, 10)}.xlsx`);
    } catch {
      // ignore export error
    }
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
              <button
                type="button"
                className="logs-page__export-btn"
                onClick={handleExport}
              >
                Excel 내보내기
              </button>
            </header>

            <LogFilter
              filters={filters}
              onFilterChange={setFilters}
              onSearch={handleSearch}
              onReset={handleReset}
            />

            <LogTable logs={logs} />

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
                총 {total} 개
              </span>
            </div>
          </div>
        </main>
      </div>
    </div>
    </>
  );
}
