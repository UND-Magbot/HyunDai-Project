"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { IconButton } from "../ui/IconButton";
import { AlarmSearchPopup } from "./AlarmSearchPopup";
import type { AlarmData, AlarmSeverity } from "@/lib/types/shell";

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

function isActiveAlarm(alarm: AlarmData): boolean {
  return !alarm.clearedAt;
}

type AlarmPopoverProps = {
  iconSrc?: string;
};

export function AlarmPopover({
  iconSrc = "/icon/Icon_v2 (41).png",
}: AlarmPopoverProps = {}) {
  const [open, setOpen] = useState(false);
  const [hasUnread, setHasUnread] = useState(true);
  const [neonAcknowledged, setNeonAcknowledged] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [soundOn, setSoundOn] = useState(true);
  const [keyword, setKeyword] = useState("");
  const triggerRef = useRef<HTMLDivElement>(null);

  const hasGlobalNeonAlert = mockAlarms.some(
    (alarm) =>
      isActiveAlarm(alarm) &&
      (alarm.severity === "warning" || alarm.severity === "error")
  );

  const showNeon = hasGlobalNeonAlert && !neonAcknowledged;

  useEffect(() => {
    document.body.removeAttribute("data-alarm-urgent");
    if (showNeon) {
      document.body.setAttribute("data-alarm-neon", "true");
    } else {
      document.body.removeAttribute("data-alarm-neon");
    }
    return () => {
      document.body.removeAttribute("data-alarm-neon");
    };
  }, [showNeon]);

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

  const displayAlarms = keyword
    ? mockAlarms.filter((a) =>
        a.message.toLowerCase().includes(keyword.toLowerCase())
      )
    : mockAlarms;

  const badgeSeverity = getHighestSeverity(mockAlarms);
  const showUnreadBadge = hasUnread && badgeSeverity;

  const handleOpenSearch = () => {
    setOpen(false);
    setSearchOpen(true);
  };

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
            setNeonAcknowledged(true);
          }}
        >
          <Image
            src={iconSrc}
            alt=""
            width={20}
            height={20}
            className="alarm-trigger__icon"
          />
        </IconButton>
        {showUnreadBadge ? (
          <span className={`alarm-badge alarm-badge--${badgeSeverity}`} />
        ) : null}

        {open ? (
          <div className="alarm-popover">
            <div className="alarm-popover__toolbar">
              <input
                type="text"
                className="alarm-popover__search-input"
                placeholder="메시지를 입력하세요."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              <IconButton
                className="alarm-popover__toolbar-btn"
                variant="ghost"
                aria-label="Alarm search"
                onClick={handleOpenSearch}
              >
                <img
                  src="/icon/search.png"
                  alt=""
                  className="alarm-popover__search-icon"
                />
              </IconButton>
              <IconButton
                className="alarm-popover__toolbar-btn"
                variant="ghost"
                aria-label={soundOn ? "Mute alarm sound" : "Enable alarm sound"}
                onClick={() => setSoundOn((v) => !v)}
              >
                <img
                  src={soundOn ? "/icon/sound-btn.png" : "/icon/sound-btn-off.png"}
                  alt={soundOn ? "Sound on" : "Sound off"}
                  className="alarm-popover__sound-icon"
                />
              </IconButton>
            </div>
            <div className="alarm-popover__list">
              {displayAlarms.length === 0 ? (
                <div className="alarm-popover__empty">No alarms</div>
              ) : (
                displayAlarms.map((alarm) => (
                  <div
                    key={alarm.id}
                    className={`alarm-item alarm-item--severity-${alarm.severity}`}
                  >
                    <div className="alarm-item__header">
                      <span className={`alarm-item__code-severity alarm-item__severity--${alarm.severity}`}>
                        [{alarm.code}] {alarm.severity.charAt(0).toUpperCase() + alarm.severity.slice(1)}
                      </span>
                      <span className="alarm-item__timestamp">
                        {alarm.occurredAt}
                      </span>
                    </div>
                    <p className="alarm-item__message">{alarm.message}</p>
                    {alarm.robot ? (
                      <span className="alarm-item__robot">{alarm.robot}</span>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </div>
        ) : null}
      </div>

      {searchOpen ? (
        <AlarmSearchPopup onClose={() => setSearchOpen(false)} />
      ) : null}
    </>
  );
}


