"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { CustomTasksTable } from "./CustomTasksTable";
import { CustomTaskModal } from "./CustomTaskModal";
import { ConfirmModal } from "../robots/ConfirmModal";
import { mockCustomTasks, BUSINESS_OPTIONS } from "@/lib/mock/customTasks";
import type { CustomTask } from "@/lib/types/custom-tasks";
import "./CustomTasksTab.css";

const PAGE_SIZE = 10;
const PAGE_GROUP = 5;

export function CustomTasksTab() {
  const [tasks, setTasks] = useState<CustomTask[]>(() =>
    mockCustomTasks.map((t) => ({ ...t, steps: t.steps.map((s) => ({ ...s })) }))
  );

  // ─── Filter state ───
  const [businessFilter, setBusinessFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [appliedBusiness, setAppliedBusiness] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");

  // ─── Pagination ───
  const [page, setPage] = useState(1);

  // ─── Modals ───
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [editTaskId, setEditTaskId] = useState<string | null>(null);
  const [deleteTaskId, setDeleteTaskId] = useState<string | null>(null);

  // ─── Filtering ───
  const filtered = useMemo(() => {
    let result = tasks;
    if (appliedBusiness) {
      result = result.filter((t) => t.business === appliedBusiness);
    }
    if (appliedKeyword) {
      const kw = appliedKeyword.toLowerCase();
      result = result.filter((t) =>
        t.taskName.toLowerCase().includes(kw)
      );
    }
    return result;
  }, [tasks, appliedBusiness, appliedKeyword]);

  // ─── Pagination ───
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page]
  );

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [totalPages, page]);

  const pageGroupStart =
    Math.floor((page - 1) / PAGE_GROUP) * PAGE_GROUP + 1;
  const pageNumbers = Array.from(
    { length: Math.min(PAGE_GROUP, totalPages - pageGroupStart + 1) },
    (_, i) => pageGroupStart + i
  );

  const handleSearch = useCallback(() => {
    setAppliedKeyword(keyword);
    setAppliedBusiness(businessFilter);
    setPage(1);
  }, [keyword, businessFilter]);

  // ─── CRUD ───
  const handleAdd = useCallback(() => {
    setEditTaskId(null);
    setTaskModalOpen(true);
  }, []);

  const handleEdit = useCallback((taskId: string) => {
    setEditTaskId(taskId);
    setTaskModalOpen(true);
  }, []);

  const handleDelete = useCallback((taskId: string) => {
    setDeleteTaskId(taskId);
  }, []);

  const handleTaskSave = useCallback((task: CustomTask) => {
    setTasks((prev) => {
      const idx = prev.findIndex((t) => t.id === task.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = task;
        return next;
      }
      return [...prev, task];
    });
  }, []);

  const handleDeleteConfirm = useCallback(() => {
    if (!deleteTaskId) return;
    setTasks((prev) => prev.filter((t) => t.id !== deleteTaskId));
    setDeleteTaskId(null);
  }, [deleteTaskId]);

  const deleteTask = deleteTaskId
    ? tasks.find((t) => t.id === deleteTaskId)
    : null;

  const editTask = editTaskId
    ? tasks.find((t) => t.id === editTaskId) ?? null
    : null;

  return (
    <section className="settings-section">
      {/* Filter bar */}
      <div className="ct-filters">
        <select
          className="ct-filters__select"
          value={businessFilter}
          onChange={(e) => setBusinessFilter(e.target.value)}
        >
          <option value="">All Business</option>
          {BUSINESS_OPTIONS.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>

        <input
          type="text"
          className="settings-search__input"
          placeholder="Search by TaskName"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
        />
        <button className="settings-search__btn" onClick={handleSearch}>
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>

        <button className="ct-filters__add-btn" onClick={handleAdd}>
          + Add
        </button>
      </div>

      {/* Table */}
      <CustomTasksTable
        tasks={paged}
        onEdit={handleEdit}
        onDelete={handleDelete}
      />

      {/* Pagination */}
      <div className="pagination">
        <button
          className="pagination__btn"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          Prev
        </button>
        {pageNumbers.map((num) => (
          <button
            key={num}
            className={`pagination__num${num === page ? " pagination__num--active" : ""}`}
            onClick={() => setPage(num)}
          >
            {num}
          </button>
        ))}
        <button
          className="pagination__btn"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
        <span className="pagination__info">{filtered.length} items</span>
      </div>

      {/* Add/Edit Task Modal */}
      <CustomTaskModal
        open={taskModalOpen}
        onClose={() => {
          setTaskModalOpen(false);
          setEditTaskId(null);
        }}
        onSave={handleTaskSave}
        editTask={editTask}
      />

      {/* Delete Confirm Modal */}
      <ConfirmModal
        open={!!deleteTaskId}
        title="작업 삭제"
        message={`"${deleteTask?.taskName ?? ""}"  작업을 삭제하시겠습니까?`}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTaskId(null)}
      />
    </section>
  );
}
