"use client";

import { DatePicker } from "./DatePicker";
import { TimeRangePicker } from "./TimeRangePicker";
import type { LogFilterState, LogType, LogTag } from "@/lib/types/logs";
import "./LogFilter.css";

type LogFilterProps = {
  filters: LogFilterState;
  robotSns: string[];
  onFilterChange: (filters: LogFilterState) => void;
  onSearch: () => void;
};

const LOG_TYPES: LogType[] = [
  "Request",
  "Response",
  "Receive",
  "Send",
  "Event",
  "Logic",
  "Error",
];

const LOG_TAGS: LogTag[] = [
  "OpentcsAPI",
  "WebEvent",
  "AppEvent",
  "LogicEvent",
  "ProcessEvent",
  "VehicleEvent",
  "TransportOrderEvent",
  "ModelEvent",
  "ConnectionEvent",
];

export function LogFilter({
  filters,
  robotSns,
  onFilterChange,
  onSearch,
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
        <label className="log-filter__label">로봇 SN</label>
        <select
          className="log-filter__select"
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

      <div className="log-filter__field">
        <label className="log-filter__label">로그 유형</label>
        <select
          className="log-filter__select"
          value={filters.logType}
          onChange={(e) =>
            update({ logType: e.target.value as LogFilterState["logType"] })
          }
        >
          <option value="">전체</option>
          {LOG_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      <div className="log-filter__field">
        <label className="log-filter__label">로그 세부 유형</label>
        <select
          className="log-filter__select"
          value={filters.logTag}
          onChange={(e) =>
            update({ logTag: e.target.value as LogFilterState["logTag"] })
          }
        >
          <option value="">전체</option>
          {LOG_TAGS.map((t) => (
            <option key={t} value={t}>
              {t}
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
        />
      </div>

      <button type="button" className="btn btn--primary" onClick={onSearch}>
        조회
      </button>
    </div>
  );
}
