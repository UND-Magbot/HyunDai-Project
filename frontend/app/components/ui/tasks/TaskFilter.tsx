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
          placeholder="작업 Num을 입력하세요."
          value={filters.waybillNum}
          onChange={(e) => update({ waybillNum: e.target.value })}
          onKeyDown={handleKeyDown}
        />
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">로봇 SN</label>
        <select
          className="task-filter__select"
          value={filters.robotSn}
          onChange={(e) => update({ robotSn: e.target.value })}
        >
          <option value="">전체</option>
          {robotSns.map((sn) => (
            <option key={sn} value={sn}>
              {sn}
            </option>
          ))}
        </select>
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">작업 유형</label>
        <select
          className="task-filter__select"
          value={filters.taskType}
          onChange={(e) =>
            update({ taskType: e.target.value as TaskListFilterState["taskType"] })
          }
        >
          <option value="">전체</option>
          <option value="Jacking">잭킹</option>
          <option value="Transport">운송</option>
          <option value="Disinfect">소독</option>
          <option value="Charge">충전</option>
          <option value="Park">주차</option>
        </select>
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">상태</label>
        <select
          className="task-filter__select"
          value={filters.state}
          onChange={(e) =>
            update({ state: e.target.value as TaskListFilterState["state"] })
          }
        >
          <option value="">전체</option>
          <option value="FINISHED">완료</option>
          <option value="WAITING">대기</option>
          <option value="InPROGRESS">진행중</option>
          <option value="PAUSED">일시 중지</option>
          <option value="UNROUTABLE">배차 불가</option>
          <option value="FAILED">실패</option>
        </select>
      </div>

      <div className="task-filter__field">
        <label className="task-filter__label">조회 기간</label>
        <DateRangePicker
          startDate={filters.dateStart}
          endDate={filters.dateEnd}
          onChange={(start, end) => update({ dateStart: start, dateEnd: end })}
        />
      </div>

      <button type="button" className="btn btn--primary" onClick={onSearch}>
        조회
      </button>
    </div>
  );
}
