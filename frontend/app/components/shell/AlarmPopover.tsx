"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IconButton } from "../ui/IconButton";
import { AlarmListItem } from "./AlarmListItem";
import { AlarmDetail } from "./AlarmDetail";
import type { AlarmData, AlarmDetailData, AlarmSeverity, FilterType } from "@/lib/types/shell";

const mockAlarms: AlarmData[] = [
  {
    id: "1",
    code: "ERR-001",
    severity: "error",
    timestamp: "2026-02-10 14:30",
    message:
      "Robot A-01 communication lost. Check network connection and verify the robot is powered on.",
    robot: "Robot A-01",
    occurredAt: "2026-02-10 14:30:12",
  },
  {
    id: "2",
    code: "WRN-012",
    severity: "warning",
    timestamp: "2026-02-10 14:25",
    message: "Battery level below 20% on Robot B-12",
    robot: "Robot B-12",
    occurredAt: "2026-02-10 14:25:03",
  },
  {
    id: "3",
    code: "INF-003",
    severity: "info",
    timestamp: "2026-02-10 14:20",
    message: "Robot C-07 task completed successfully",
    robot: "Robot C-07",
    occurredAt: "2026-02-10 14:20:45",
    clearedAt: "2026-02-10 14:20:45",
  },
];

const severityPriority: Record<AlarmSeverity, number> = {
  error: 3,
  warning: 2,
  info: 1,
};

function getHighestSeverity(alarms: AlarmData[]): AlarmSeverity | null {
  if (alarms.length === 0) return null;
  let highest: AlarmSeverity = "info";
  for (const alarm of alarms) {
    if (severityPriority[alarm.severity] > severityPriority[highest]) {
      highest = alarm.severity;
    }
  }
  return highest;
}

export function AlarmPopover() {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");
  const [selectedAlarm, setSelectedAlarm] = useState<AlarmDetailData | null>(
    null
  );
  const [hasUnread, setHasUnread] = useState(true);
  const triggerRef = useRef<HTMLDivElement>(null);

  const hasUrgent =
    hasUnread && mockAlarms.some((a) => a.severity === "error");

  useEffect(() => {
    if (hasUrgent) {
      document.body.setAttribute("data-alarm-urgent", "true");
    } else {
      document.body.removeAttribute("data-alarm-urgent");
    }
    return () => {
      document.body.removeAttribute("data-alarm-urgent");
    };
  }, [hasUrgent]);

  const handleClose = useCallback(() => {
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        handleClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open, handleClose]);

  const filteredAlarms =
    filter === "all"
      ? mockAlarms
      : mockAlarms.filter((a) => a.severity === filter);

  const badgeSeverity = getHighestSeverity(mockAlarms);

  const handleAlarmClick = (alarm: AlarmData) => {
    setSelectedAlarm({
      id: alarm.id,
      code: alarm.code,
      severity: alarm.severity,
      message: alarm.message,
      robot: alarm.robot,
      occurredAt: alarm.occurredAt,
      clearedAt: alarm.clearedAt,
    });
  };

  const filters: { key: FilterType; label: string }[] = [
    { key: "all", label: "All" },
    { key: "info", label: "Info" },
    { key: "warning", label: "Warning" },
    { key: "error", label: "Error" },
  ];

  return (
    <>
      <div className="alarm-trigger" ref={triggerRef}>
        <IconButton
          className="alarm-trigger__btn"
          variant="ghost"
          aria-label="Open alarms"
          onClick={() => {
            setOpen((v) => !v);
            setHasUnread(false);
          }}
        >
          🔔
        </IconButton>
        {badgeSeverity ? (
          <span className={`alarm-badge alarm-badge--${badgeSeverity}`} />
        ) : null}

        {open ? (
          <div className="alarm-popover">
            <div className="alarm-popover__header">
              <h3 className="alarm-popover__title">Alarms</h3>
              <div className="alarm-popover__filters">
                {filters.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    className={
                      filter === f.key
                        ? "alarm-popover__filter alarm-popover__filter--active"
                        : "alarm-popover__filter"
                    }
                    onClick={() => setFilter(f.key)}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="alarm-popover__list">
              {filteredAlarms.length === 0 ? (
                <div className="alarm-popover__empty">No alarms</div>
              ) : (
                filteredAlarms.map((alarm) => (
                  <AlarmListItem
                    key={alarm.id}
                    code={alarm.code}
                    severity={alarm.severity}
                    timestamp={alarm.timestamp}
                    message={alarm.message}
                    onClick={() => handleAlarmClick(alarm)}
                  />
                ))
              )}
            </div>
          </div>
        ) : null}
      </div>

      {selectedAlarm ? (
        <AlarmDetail
          alarm={selectedAlarm}
          onClose={() => setSelectedAlarm(null)}
        />
      ) : null}
    </>
  );
}
