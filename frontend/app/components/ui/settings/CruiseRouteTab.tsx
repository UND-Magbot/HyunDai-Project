"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { CruiseRouteTable } from "./CruiseRouteTable";
import { CruiseRouteModal } from "./CruiseRouteModal";
import { ConfirmModal } from "../robots/ConfirmModal";
import { mockCruiseRoutes } from "@/lib/mock/cruiseRoutes";
import type { CruiseRoute } from "@/lib/types/cruise-route";
import "./CruiseRouteTab.css";

const PAGE_SIZE = 10;
const PAGE_GROUP = 5;

export function CruiseRouteTab() {
  const [routes, setRoutes] = useState<CruiseRoute[]>(() =>
    mockCruiseRoutes.map((r) => ({ ...r, sites: r.sites.map((s) => ({ ...s })) }))
  );

  // ─── Pagination ───
  const [page, setPage] = useState(1);

  // ─── Modals ───
  const [modalOpen, setModalOpen] = useState(false);
  const [editRouteId, setEditRouteId] = useState<string | null>(null);
  const [deleteRouteId, setDeleteRouteId] = useState<string | null>(null);

  // ─── Pagination ───
  const totalPages = Math.max(1, Math.ceil(routes.length / PAGE_SIZE));
  const paged = useMemo(
    () => routes.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [routes, page]
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

  // ─── CRUD ───
  const handleAdd = useCallback(() => {
    setEditRouteId(null);
    setModalOpen(true);
  }, []);

  const handleEdit = useCallback((routeId: string) => {
    setEditRouteId(routeId);
    setModalOpen(true);
  }, []);

  const handleDelete = useCallback((routeId: string) => {
    setDeleteRouteId(routeId);
  }, []);

  const handleSave = useCallback((route: CruiseRoute) => {
    setRoutes((prev) => {
      const idx = prev.findIndex((r) => r.id === route.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = route;
        return next;
      }
      return [...prev, route];
    });
  }, []);

  const handleDeleteConfirm = useCallback(() => {
    if (!deleteRouteId) return;
    setRoutes((prev) => prev.filter((r) => r.id !== deleteRouteId));
    setDeleteRouteId(null);
  }, [deleteRouteId]);

  const deleteRoute = deleteRouteId
    ? routes.find((r) => r.id === deleteRouteId)
    : null;

  const editRoute = editRouteId
    ? routes.find((r) => r.id === editRouteId) ?? null
    : null;

  return (
    <section className="settings-section">
      {/* Header */}
      <div className="cr-header">
        <button className="cr-header__add-btn" onClick={handleAdd}>
          Add Settings
        </button>
      </div>

      {/* Table */}
      <CruiseRouteTable
        routes={paged}
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
        <span className="pagination__info">{routes.length} items</span>
      </div>

      {/* Add/Edit Modal */}
      <CruiseRouteModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditRouteId(null);
        }}
        onSave={handleSave}
        editRoute={editRoute}
      />

      {/* Delete Confirm Modal */}
      <ConfirmModal
        open={!!deleteRouteId}
        title="Delete Route"
        message={`Are you sure to delete ${deleteRoute?.routeName ?? ""}?`}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteRouteId(null)}
      />
    </section>
  );
}
