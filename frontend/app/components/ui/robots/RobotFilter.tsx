"use client";

import type { RobotFilterProps, RobotFilterState } from "@/lib/types/robots";
import "./RobotFilter.css";

export function RobotFilter({
  filters,
  models,
  onFilterChange,
  onSearch,
}: RobotFilterProps) {
  const update = (patch: Partial<RobotFilterState>) => {
    onFilterChange({ ...filters, ...patch });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSearch();
  };

  return (
    <div className="robot-filter">
      <div className="robot-filter__field robot-filter__field--search">
        <input
          type="text"
          className="robot-filter__input"
          placeholder="SN or Name 입력하세요."
          value={filters.searchText}
          onChange={(e) => update({ searchText: e.target.value })}
          onKeyDown={handleKeyDown}
        />
      </div>

      <div className="robot-filter__field">
        <label className="robot-filter__label">Model</label>
        <select
          className="robot-filter__select"
          value={filters.model}
          onChange={(e) => update({ model: e.target.value })}
        >
          <option value="">All</option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div className="robot-filter__field">
        <label className="robot-filter__label">State</label>
        <select
          className="robot-filter__select"
          value={filters.runState}
          onChange={(e) =>
            update({ runState: e.target.value as RobotFilterState["runState"] })
          }
        >
          <option value="">All</option>
          <option value="EXECUTING">EXECUTING</option>
          <option value="IDLE">IDLE</option>
          <option value="CHARGING">CHARGING</option>
        </select>
      </div>

      <div className="robot-filter__field">
        <label className="robot-filter__label">Power</label>
        <select
          className="robot-filter__select"
          value={filters.online}
          onChange={(e) =>
            update({ online: e.target.value as RobotFilterState["online"] })
          }
        >
          <option value="">All</option>
          <option value="Online">Online</option>
          <option value="Offline">Offline</option>
        </select>
      </div>

      <div className="robot-filter__field">
        <label className="robot-filter__label">Enable</label>
        <select
          className="robot-filter__select"
          value={filters.enable}
          onChange={(e) =>
            update({ enable: e.target.value as RobotFilterState["enable"] })
          }
        >
          <option value="">All</option>
          <option value="Enable">Enable</option>
          <option value="Disabled">Disabled</option>
        </select>
      </div>

      <button type="button" className="btn btn--primary" onClick={onSearch}>
        검색
      </button>
    </div>
  );
}
