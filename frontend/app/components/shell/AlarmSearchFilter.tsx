"use client";

import { DatePicker } from "../ui/logs/DatePicker";
import { TimeRangePicker } from "../ui/logs/TimeRangePicker";
import type { AlarmSearchFilterProps } from "@/lib/types/alarm-search";

export function AlarmSearchFilter({
  filters,
  robotSns,
  onFilterChange,
  onSearch,
}: AlarmSearchFilterProps) {
  const update = (patch: Partial<typeof filters>) => {
    onFilterChange({ ...filters, ...patch });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSearch();
  };

  return (
    <div className="alarm-search-filter">
      <div className="alarm-search-filter__row">
        <div className="alarm-search-filter__field alarm-search-filter__field--search">
          <input
            type="text"
            className="alarm-search-filter__input"
            placeholder="Message"
            value={filters.message}
            onChange={(e) => update({ message: e.target.value })}
            onKeyDown={handleKeyDown}
          />
        </div>

        <div className="alarm-search-filter__field alarm-search-filter__field--sn">
          <label className="alarm-search-filter__label">Robot SN</label>
          <select
            className="alarm-search-filter__select"
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
      </div>

      <div className="alarm-search-filter__row">
        <div className="alarm-search-filter__field">
          <label className="alarm-search-filter__label">Date</label>
          <DatePicker
            value={filters.date}
            onChange={(date) => update({ date })}
          />
        </div>

        <div className="alarm-search-filter__field">
          <label className="alarm-search-filter__label">Time</label>
          <TimeRangePicker
            startTime={filters.startTime}
            endTime={filters.endTime}
            onChange={(startTime, endTime) => update({ startTime, endTime })}
          />
        </div>

        <button type="button" className="btn btn--primary" onClick={onSearch}>
          검색
        </button>
      </div>
    </div>
  );
}
