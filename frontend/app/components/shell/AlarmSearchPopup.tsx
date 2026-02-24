"use client";

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { IconButton } from "../ui/IconButton";
import { AlarmSearchFilter } from "./AlarmSearchFilter";
import { AlarmSearchItem } from "./AlarmSearchItem";
import { AlarmSearchPagination } from "./AlarmSearchPagination";
import {
  searchAlarms,
  getDistinctAlarmRobotSNs,
  getDistinctAlarmCodes,
} from "@/lib/mock/alarmSearch";
import { ALARM_ERROR_TYPE_LABELS } from "@/lib/constants/alarm";
import type {
  AlarmSearchFilterState,
  AlarmSearchResponse,
} from "@/lib/types/alarm-search";
import "./alarm-search.css";

type AlarmSearchPopupProps = {
  onClose: () => void;
};

const defaultFilters: AlarmSearchFilterState = {
  message: "",
  errorType: "",
  code: "",
  robotSn: "",
  date: null,
  startTime: "00:00",
  endTime: "23:59",
};

export function AlarmSearchPopup({ onClose }: AlarmSearchPopupProps) {
  const [filters, setFilters] = useState<AlarmSearchFilterState>(defaultFilters);
  const [appliedFilters, setAppliedFilters] =
    useState<AlarmSearchFilterState>(defaultFilters);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(6);
  const [results, setResults] = useState<AlarmSearchResponse>({
    items: [],
    total: 0,
    page: 1,
    pageSize: 6,
  });

  const dialogRef = useRef<HTMLDivElement>(null);
  const robotSns = useMemo(() => getDistinctAlarmRobotSNs(), []);
  const codes = useMemo(() => getDistinctAlarmCodes(), []);
  const errorTypes = useMemo(
    () =>
      Object.entries(ALARM_ERROR_TYPE_LABELS).map(([value, label]) => ({
        value,
        label,
      })),
    []
  );

  const doSearch = useCallback(
    (f: AlarmSearchFilterState, p: number, ps: number) => {
      const res = searchAlarms({
        ...f,
        page: p,
        pageSize: ps,
      });
      setResults(res);
    },
    []
  );

  // Initial load
  useEffect(() => {
    doSearch(appliedFilters, page, pageSize);
  }, [appliedFilters, page, pageSize, doSearch]);

  // ESC to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
      onClose();
    }
  };

  const handleSearch = () => {
    setAppliedFilters({ ...filters });
    setPage(1);
  };

  const handleReset = () => {
    setFilters(defaultFilters);
    setAppliedFilters(defaultFilters);
    setPage(1);
  };

  const handlePageSizeChange = (newSize: number) => {
    setPageSize(newSize);
    setPage(1);
  };

  return (
    <div className="alarm-search__overlay" onMouseDown={handleOverlayClick}>
      <div className="alarm-search" ref={dialogRef} role="dialog" aria-label="Alarm search">
        <div className="alarm-search__header">
          <h2 className="alarm-search__title">알람 검색</h2>
          <IconButton
            className="alarm-search__close"
            variant="ghost"
            aria-label="Close"
            onClick={onClose}
          >
            ✕
          </IconButton>
        </div>

        <AlarmSearchFilter
          filters={filters}
          robotSns={robotSns}
          errorTypes={errorTypes}
          codes={codes}
          onFilterChange={setFilters}
          onSearch={handleSearch}
          onReset={handleReset}
        />

        <div className="alarm-search__list">
          {results.items.length === 0 ? (
            <div className="alarm-search__empty">검색 결과가 없습니다.</div>
          ) : (
            results.items.map((item) => (
              <AlarmSearchItem key={item.id} item={item} />
            ))
          )}
        </div>

        {results.total > 0 ? (
          <AlarmSearchPagination
            page={page}
            pageSize={pageSize}
            total={results.total}
            onPageChange={setPage}
            onPageSizeChange={handlePageSizeChange}
          />
        ) : null}
      </div>
    </div>
  );
}
