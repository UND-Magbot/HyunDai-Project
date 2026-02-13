"use client";

import type { AlarmSearchItemProps } from "@/lib/types/alarm-search";

export function AlarmSearchItem({ item }: AlarmSearchItemProps) {
  const statusClass =
    item.status === "Warning"
      ? "alarm-search-item__status--warning"
      : "alarm-search-item__status--resume";

  return (
    <div className="alarm-search-item">
      <div className="alarm-search-item__row">
        <span className="alarm-search-item__dot" />
        <span className="alarm-search-item__line">
          <span className="alarm-search-item__code">[{item.code}]</span>{" "}
          <span className={statusClass}>{item.status}</span>{" "}
          <span className="alarm-search-item__sn">{item.robotSn}</span>{" "}
          <span className="alarm-search-item__message">{item.message}</span>
        </span>
      </div>
      <div className="alarm-search-item__timestamp">{item.timestamp}</div>
    </div>
  );
}
