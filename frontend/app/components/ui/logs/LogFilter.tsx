"use client";

import { DatePicker } from "./DatePicker";
import { TimeRangePicker } from "./TimeRangePicker";
import type { LogFilterState, ErrorCategory } from "@/lib/types/logs";
import "./LogFilter.css";

type LogFilterProps = {
  filters: LogFilterState;
  onFilterChange: (filters: LogFilterState) => void;
  onSearch: () => void;
  onReset: () => void;
};

const ERROR_CATEGORIES: ErrorCategory[] = ["시스템", "로봇", "사용자"];

export function LogFilter({
  filters,
  onFilterChange,
  onSearch,
  onReset,
}: LogFilterProps) {
  const update = (patch: Partial<LogFilterState>) => {
    onFilterChange({ ...filters, ...patch });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSearch();
  };

  return (
    <div className="log-filter">
      <div className="log-filter__field log-filter__field--search">
        <input
          type="text"
          className="log-filter__input"
          placeholder="로그 메세지를 입력하세요."
          value={filters.message}
          onChange={(e) => update({ message: e.target.value })}
          onKeyDown={handleKeyDown}
        />
      </div>

      <div className="log-filter__field">
        <label className="log-filter__label">로그 타입</label>
        <select
          className="log-filter__select"
          value={filters.errorType}
          onChange={(e) =>
            update({ errorType: e.target.value as LogFilterState["errorType"] })
          }
        >
          <option value="">전체</option>
          {ERROR_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div className="log-filter__field">
        <label className="log-filter__label">조회 날짜</label>
        <DatePicker
          value={filters.date}
          onChange={(date) => update({ date })}
        />
      </div>

      <div className="log-filter__field">
        <label className="log-filter__label">조회 시간</label>
        <TimeRangePicker
          startTime={filters.startTime}
          endTime={filters.endTime}
          onChange={(startTime, endTime) => update({ startTime, endTime })}
          disabled={!filters.date}
        />
      </div>

      <button type="button" className="btn" onClick={onReset}>
        초기화
      </button>
      <button type="button" className="btn btn--primary" onClick={onSearch}>
        조회
      </button>
    </div>
  );
}
