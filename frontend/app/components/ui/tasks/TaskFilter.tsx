"use client";

import { DateRangePicker } from "./DateRangePicker";
import type { TaskListFilterProps, TaskListFilterState } from "@/lib/types/tasks";
import "./TaskFilter.css";

export function TaskFilter({
  filters,
  robotSns,
  onFilterChange,
  onSearch,
}: TaskListFilterProps) {
  const update = (patch: Partial<TaskListFilterState>) => {
    onFilterChange({ ...filters, ...patch });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSearch();
  };

  return (
    <div className="task-filter">
      <div className="task-filter__field task-filter__field--search">
        <input
          type="text"
          className="task-filter__input"
          placeholder="waybill number를 입력하세요."
          value={filters.waybillNum}
          onChange={(e) => update({ waybillNum: e.target.value })}
          onKeyDown={handleKeyDown}
        />
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">Robot SN</label>
        <select
          className="task-filter__select"
          value={filters.robotSn}
          onChange={(e) => update({ robotSn: e.target.value })}
        >
          <option value="">All</option>
          {robotSns.map((sn) => (
            <option key={sn} value={sn}>
              {sn}
            </option>
          ))}
        </select>
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">Task Type</label>
        <select
          className="task-filter__select"
          value={filters.taskType}
          onChange={(e) =>
            update({ taskType: e.target.value as TaskListFilterState["taskType"] })
          }
        >
          <option value="">All</option>
          <option value="Jacking">Jacking</option>
          <option value="Transport">Transport</option>
          <option value="Disinfect">Disinfect</option>
          <option value="Charge">Charge</option>
          <option value="Park">Park</option>
        </select>
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">State</label>
        <select
          className="task-filter__select"
          value={filters.state}
          onChange={(e) =>
            update({ state: e.target.value as TaskListFilterState["state"] })
          }
        >
          <option value="">All</option>
          <option value="FINISHED">FINISHED</option>
          <option value="WAITING">WAITING</option>
          <option value="InPROGRESS">InPROGRESS</option>
          <option value="PAUSED">PAUSED</option>
          <option value="UNROUTABLE">UNROUTABLE</option>
          <option value="FAILED">FAILED</option>
        </select>
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">Date Range</label>
        <DateRangePicker
          startDate={filters.dateStart}
          endDate={filters.dateEnd}
          onChange={(start, end) => update({ dateStart: start, dateEnd: end })}
        />
      </div>

      <button type="button" className="btn btn--primary" onClick={onSearch}>
        검색
      </button>
    </div>
  );
}
