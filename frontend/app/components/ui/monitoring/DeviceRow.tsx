"use client";

import { IconButton } from "../IconButton";
import type { DeviceRowProps } from "@/lib/types/monitoring";

export function DeviceRow({
  id,
  name,
  taskCount,
  power,
  battery,
  status,
  isExpanded = false,
  onToggleExpand,
  onInfo,
}: DeviceRowProps) {
  const expanded = isExpanded;
  const isOffline = power === "offline";
  const isRunning = status === "running";
  const isInvalidOnlineDisable = power === "online" && status === "disable";
  const effectiveStatus = isOffline ? "disable" : status;
  const actionLabel = isOffline ? "활성" : "비활성";

  const canSuspend = !isOffline && !isInvalidOnlineDisable && isRunning;
  const canActionButton = isOffline || (!isInvalidOnlineDisable && isRunning);
  const canNav = !isOffline && !isInvalidOnlineDisable;
  const canInfo = !isInvalidOnlineDisable;

  return (
    <div 
      className={`device-row${expanded ? " device-row--expanded" : ""}`}
      onClick={() => onToggleExpand?.(id)}
    >
      <button
        type="button"
        className="device-row__summary"
        aria-expanded={expanded}
      >
        <span className="device-row__cell device-row__cell--robot">{name}</span>
        <span className="device-row__cell device-row__cell--task">{taskCount ?? 0}</span>
        <span className={`device-row__cell device-row__cell--power power--${power}`}>{power}</span>
        <span className="device-row__cell device-row__cell--battery">
          {battery}
        </span>
        <span className="device-row__cell device-row__cell--status">
          <span className={`status-chip status-chip--${effectiveStatus}`}>
            {effectiveStatus}
          </span>
        </span>
      </button>
      {expanded ? (
        <div
          className="device-row__actions"
          onClick={(event) => event.stopPropagation()}
        >
          <IconButton aria-label="Suspend" disabled={!canSuspend}>
            정지
          </IconButton>
          <IconButton aria-label={actionLabel} disabled={!canActionButton}>
            {actionLabel}
          </IconButton>
          <IconButton aria-label="Navigate" disabled={!canNav}>
            네비
          </IconButton>
          <IconButton
            aria-label="Info"
            disabled={!canInfo}
            onClick={() => onInfo?.(id)}
          >
            정보
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}
