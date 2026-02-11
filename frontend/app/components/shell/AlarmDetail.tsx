"use client";

import { useEffect, useRef } from "react";
import { IconButton } from "../ui/IconButton";
import type { AlarmSeverity, AlarmDetailProps } from "@/lib/types/shell";

const severityLabels: Record<AlarmSeverity, string> = {
  info: "Info",
  warning: "Warning",
  error: "Error",
};

export function AlarmDetail({ alarm, onClose }: AlarmDetailProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  return (
    <div
      className="alarm-detail__overlay"
      ref={overlayRef}
      onClick={handleOverlayClick}
    >
      <div className="alarm-detail" role="dialog" aria-label="Alarm detail">
        <div className="alarm-detail__header">
          <h2 className="alarm-detail__title">
            <span className={`alarm-item__severity--${alarm.severity}`}>
              [{alarm.code}] {severityLabels[alarm.severity]}
            </span>
          </h2>
          <IconButton
            className="alarm-detail__close"
            variant="ghost"
            aria-label="Close"
            onClick={onClose}
          >
            ✕
          </IconButton>
        </div>
        <div className="alarm-detail__body">
          <div className="alarm-detail__row">
            <span className="alarm-detail__label">Message</span>
            <span className="alarm-detail__value">{alarm.message}</span>
          </div>
          {alarm.robot ? (
            <div className="alarm-detail__row">
              <span className="alarm-detail__label">Related Robot</span>
              <span className="alarm-detail__value">{alarm.robot}</span>
            </div>
          ) : null}
          <div className="alarm-detail__row">
            <span className="alarm-detail__label">Occurred</span>
            <span className="alarm-detail__value">{alarm.occurredAt}</span>
          </div>
          {alarm.clearedAt ? (
            <div className="alarm-detail__row">
              <span className="alarm-detail__label">Cleared</span>
              <span className="alarm-detail__value">{alarm.clearedAt}</span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
