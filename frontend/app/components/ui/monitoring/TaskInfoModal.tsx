"use client";

import { useMemo } from "react";
import { Modal } from "../Modal";
import { getMockTaskDetail } from "@/lib/mock/taskDetails";
import type { TaskInfoModalProps } from "@/lib/types/monitoring";
import "./TaskInfoModal.css";

function formatValue(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  return String(value);
}

function formatDuration(startTime: string, endTime: string): string {
  if (!startTime) return "-";

  const start = new Date(startTime).getTime();
  if (isNaN(start)) return "-";

  const end = endTime ? new Date(endTime).getTime() : Date.now();
  if (isNaN(end)) return "-";

  const diffMs = Math.max(0, end - start);
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return [hours, minutes, seconds]
    .map((v) => String(v).padStart(2, "0"))
    .join(":");
}

const STATUS_CLASS: Record<string, string> = {
  completed: "success",
  failed: "error",
  running: "primary",
  pending: "muted",
};

export function TaskInfoModal({ taskId, onClose }: TaskInfoModalProps) {
  const task = useMemo(
    () => (taskId ? getMockTaskDetail(taskId) : null),
    [taskId]
  );

  const renderContent = () => {
    if (!task) {
      return (
        <div className="task-info__error">
          <p>Task not found</p>
        </div>
      );
    }

    return (
      <div className="task-info">
        <section className="task-info__section">
          <h3 className="task-info__section-title">Basic Information</h3>
          <div className="task-info__grid">
            <div className="task-info__field">
              <span className="task-info__label">Waybill Number</span>
              <span
                className="task-info__value task-info__value--ellipsis"
                title={task.waybillNumber}
              >
                {formatValue(task.waybillNumber)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Business</span>
              <span className="task-info__value">
                {formatValue(task.business)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Task Type</span>
              <span className="task-info__value">
                {formatValue(task.taskType)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Priority</span>
              <span className="task-info__value">
                {formatValue(task.priority)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Start</span>
              <span className="task-info__value">
                {formatValue(task.start)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">End</span>
              <span className="task-info__value">
                {formatValue(task.end)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Pass</span>
              <span className="task-info__value">
                {formatValue(task.pass)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Time</span>
              <span className="task-info__value">
                {formatDuration(task.startTime, task.endTime)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Status</span>
              <span
                className={`task-info__badge task-info__badge--${STATUS_CLASS[task.status] ?? "muted"}`}
              >
                {task.status}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Route Mode</span>
              <span className="task-info__value">
                {formatValue(task.routeMode)}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Detour Radius</span>
              <span className="task-info__value">
                {task.detourRadius != null ? `${task.detourRadius} m` : "-"}
              </span>
            </div>
            <div className="task-info__field">
              <span className="task-info__label">Speed</span>
              <span className="task-info__value">
                {task.speed != null ? `${task.speed} m/s` : "-"}
              </span>
            </div>
          </div>
        </section>

        <section className="task-info__section">
          <h3 className="task-info__section-title">Task Log</h3>
          {task.logs.length === 0 ? (
            <div className="task-info__empty">No log data</div>
          ) : (
            <div className="task-info__log-container">
              <ul className="task-info__timeline">
                {task.logs.map((log, index) => (
                  <li key={index} className="task-info__timeline-item">
                    <span
                      className={`task-info__timeline-dot task-info__timeline-dot--${log.level}`}
                    />
                    <div className="task-info__timeline-content">
                      <span className="task-info__timeline-message">
                        {log.message}
                      </span>
                      <span className="task-info__timeline-time">
                        {log.timestamp}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>
    );
  };

  return (
    <Modal open={!!taskId} onClose={onClose} title="Task Info" width="760px">
      {renderContent()}
    </Modal>
  );
}
