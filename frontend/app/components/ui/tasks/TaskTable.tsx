"use client";

import type { TaskListTableProps, TaskListItem } from "@/lib/types/tasks";
import "./TaskTable.css";

const STATE_BADGE: Record<string, string> = {
  FINISHED: "success",
  InPROGRESS: "primary",
  WAITING: "muted",
  PAUSED: "warning",
  FAILED: "error",
  UNROUTABLE: "error",
};

function formatDuration(createTime: string, endTime: string | null): string {
  const start = new Date(createTime).getTime();
  if (isNaN(start)) return "-";
  const end = endTime ? new Date(endTime).getTime() : Date.now();
  if (isNaN(end)) return "-";
  const diffMs = Math.max(0, end - start);
  const totalSeconds = Math.floor(diffMs / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

function val(v: string | null): string {
  return v ?? "-";
}

export function TaskTable({ tasks, onInfoClick }: TaskListTableProps) {
  return (
    <div className="task-table__wrapper">
      <table className="task-table">
        <colgroup>
          <col style={{ width: "12%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "9%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "12%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "7%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>번호</th>
            <th>로봇 SN</th>
            <th>작업 상태</th>
            <th>작업 유형</th>
            <th>작업 시간</th>
            <th>시작 시간</th>
            <th>종료 시간</th>
            <th>시작 지점</th>
            <th>종료 지점</th>
            <th>경유지</th>
            <th>작업 관리</th>
          </tr>
        </thead>
        <tbody>
          {tasks.length === 0 ? (
            <tr>
              <td colSpan={11} className="task-table__empty">
                조회된 작업이 없습니다.
              </td>
            </tr>
          ) : (
            tasks.map((t) => (
              <TaskRow key={t.id} task={t} onInfoClick={onInfoClick} />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function TaskRow({
  task,
  onInfoClick,
}: {
  task: TaskListItem;
  onInfoClick: (id: string) => void;
}) {
  const badgeVariant = STATE_BADGE[task.state] ?? "muted";

  return (
    <tr>
      <td>
        <div className="task-table__num">
          <span className="task-table__waybill" title={task.waybillNumber}>
            {task.waybillNumber}
          </span>
          <span className="task-table__task-id">{task.taskId}</span>
        </div>
      </td>
      <td>{task.robotSn}</td>
      <td>
        <span className={`task-table__badge task-table__badge--${badgeVariant}`}>
          {task.state}
        </span>
      </td>
      <td>{task.taskType}</td>
      <td>{formatDuration(task.createTime, task.endTime)}</td>
      <td>{task.createTime}</td>
      <td>{val(task.endTime)}</td>
      <td>{val(task.start)}</td>
      <td>{val(task.end)}</td>
      <td>{val(task.passing)}</td>
      <td>
        <button
          type="button"
          className="task-table__info-btn"
          onClick={() => onInfoClick(task.id)}
        >
          상세보기
        </button>
      </td>
    </tr>
  );
}
