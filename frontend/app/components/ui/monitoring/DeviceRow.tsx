"use client";

import { IconButton } from "../IconButton";
import type { DevicePower, DeviceRowProps, DeviceStatus } from "@/lib/types/monitoring";

const POWER_LABEL: Record<DevicePower, string> = {
  online: "온라인",
  offline: "오프라인",
};

const STATUS_LABEL: Record<DeviceStatus, string> = {
  idle: "대기",
  running: "운행 중",
  charging: "충전 중",
  error: "오류",
  warning: "경고",
  disable: "비활성",
};

export function DeviceRow({
  id,
  name,
  power,
  battery,
  status,
  isExpanded = false,
  onToggleExpand,
  onInfo,
  onReturn,
  onStop,
}: DeviceRowProps) {
  const expanded = isExpanded;
  const isOffline = power === "offline";
  const isRunning = status === "running";
  const isInvalidOnlineDisable = power === "online" && status === "disable";
  const effectiveStatus = isOffline ? "disable" : status;

  const isCharging = status === "charging";
  const canSuspend = !isOffline && !isInvalidOnlineDisable && (isRunning || isCharging);
  const canCharge = !isOffline && !isInvalidOnlineDisable;
  const canNav = !isOffline && !isInvalidOnlineDisable;
  const canInfo = !isInvalidOnlineDisable;

  const batteryNum = parseFloat(battery);
  const isBatteryLow = Number.isFinite(batteryNum) && batteryNum <= 30;

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
        <span className={`device-row__cell device-row__cell--power power--${power}`}>{POWER_LABEL[power]}</span>
        <span className={`device-row__cell device-row__cell--battery${isBatteryLow ? " battery--danger" : ""}`}>
          {battery}
        </span>
        <span className="device-row__cell device-row__cell--status">
          <span className={`status-chip status-chip--${effectiveStatus}`}>
            {STATUS_LABEL[effectiveStatus]}
          </span>
        </span>
      </button>
      {expanded ? (
        <div
          className="device-row__actions"
          onClick={(event) => event.stopPropagation()}
        >
          <IconButton aria-label="Suspend" disabled={!canSuspend} onClick={() => onStop?.(id)}>
            정지
          </IconButton>
          <IconButton aria-label="Return" disabled={!canCharge} onClick={() => onReturn?.(id)}>
            복귀
          </IconButton>
          {/* <IconButton aria-label="Navigate" disabled={!canNav}>
            네비
          </IconButton> */}
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
