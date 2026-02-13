"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { TopBar } from "../components/shell/TopBar";
import { SideNav, defaultNavItems } from "../components/shell/SideNav";
import { TaskFilter } from "../components/ui/tasks/TaskFilter";
import { TaskTable } from "../components/ui/tasks/TaskTable";
import { TaskInfoModal } from "../components/ui/monitoring/TaskInfoModal";
import {
  mockTaskList,
  getDistinctRobotSNs,
} from "@/lib/mock/taskList";
import type { TaskListFilterState, TaskListItem } from "@/lib/types/tasks";
import "./tasks.css";

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

const defaultFilters: TaskListFilterState = {
  waybillNum: "",
  robotSn: "",
  taskType: "",
  state: "",
  dateStart: null,
  dateEnd: null,
};

function applyFilters(
  tasks: TaskListItem[],
  filters: TaskListFilterState
): TaskListItem[] {
  return tasks.filter((t) => {
    if (filters.waybillNum) {
      const keyword = filters.waybillNum.toLowerCase();
      if (!t.waybillNumber.toLowerCase().includes(keyword)) return false;
    }
    if (filters.robotSn && t.robotSn !== filters.robotSn) return false;
    if (filters.taskType && t.taskType !== filters.taskType) return false;
    if (filters.state && t.state !== filters.state) return false;
    if (filters.dateStart) {
      const taskDate = t.createTime.slice(0, 10);
      if (taskDate < filters.dateStart) return false;
    }
    if (filters.dateEnd) {
      const taskDate = t.createTime.slice(0, 10);
      if (taskDate > filters.dateEnd) return false;
    }
    return true;
  });
}

const PAGE_SIZE = 10;
const PAGE_GROUP = 5;

export default function TasksPage() {
  const [navCollapsed, setNavCollapsed] = useState(true);
  const [currentDateTime, setCurrentDateTime] = useState(formatDateTime);

  useEffect(() => {
    const timer = setInterval(() => setCurrentDateTime(formatDateTime()), 1000);
    return () => clearInterval(timer);
  }, []);

  const [tasks] = useState<TaskListItem[]>(mockTaskList);
  const [filters, setFilters] = useState<TaskListFilterState>(defaultFilters);
  const [searchFilters, setSearchFilters] = useState<TaskListFilterState>(defaultFilters);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const robotSns = useMemo(() => getDistinctRobotSNs(tasks), [tasks]);

  const displayTasks = useMemo(
    () => applyFilters(tasks, searchFilters),
    [tasks, searchFilters]
  );

  const totalPages = Math.max(1, Math.ceil(displayTasks.length / PAGE_SIZE));

  const pagedTasks = useMemo(
    () =>
      displayTasks.slice(
        (currentPage - 1) * PAGE_SIZE,
        currentPage * PAGE_SIZE
      ),
    [displayTasks, currentPage]
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchFilters]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [totalPages, currentPage]);

  const pageGroupStart =
    Math.floor((currentPage - 1) / PAGE_GROUP) * PAGE_GROUP + 1;
  const pageNumbers = Array.from(
    { length: Math.min(PAGE_GROUP, totalPages - pageGroupStart + 1) },
    (_, i) => pageGroupStart + i
  );

  const handleSearch = useCallback(() => {
    setSearchFilters({ ...filters });
  }, [filters]);

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
          <div className="tasks-page">
            <header className="tasks-page__header">
              <h1 className="tasks-page__title">작업 관리</h1>
            </header>

            <TaskFilter
              filters={filters}
              robotSns={robotSns}
              onFilterChange={setFilters}
              onSearch={handleSearch}
            />

            <TaskTable tasks={pagedTasks} onInfoClick={setSelectedTaskId} />

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
                {displayTasks.length} items
              </span>
            </div>
          </div>

          <TaskInfoModal
            taskId={selectedTaskId}
            onClose={() => setSelectedTaskId(null)}
          />
        </main>
      </div>
    </div>
  );
}
