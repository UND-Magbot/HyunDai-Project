"use client";

import { useState, useEffect } from "react";
import type { MapFloatingPanelProps } from "@/lib/types/map";

export function MapFloatingPanel({
  open,
  onToggle,
  robotConnected,
  onStartMapping,
  onClearMap,
  onRemoteImage,
  onRemoteControl,
}: MapFloatingPanelProps) {
  const [visible, setVisible] = useState(open);
  const [animating, setAnimating] = useState<"in" | "out" | null>(null);

  useEffect(() => {
    if (open) {
      setVisible(true);
      setAnimating("in");
    } else if (visible) {
      setAnimating("out");
    }
  }, [open]);

  const handleAnimationEnd = () => {
    if (animating === "out") {
      setVisible(false);
    }
    setAnimating(null);
  };

  const contentClass = [
    "map-floating-panel__content",
    animating === "in" ? "map-floating-panel__content--slide-in" : "",
    animating === "out" ? "map-floating-panel__content--slide-out" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="map-floating-panel">
      {visible ? (
        <div className={contentClass} onAnimationEnd={handleAnimationEnd}>
          <button
            className="map-floating-panel__toggle"
            onClick={onToggle}
            title="패널 닫기"
          >
            ▸
          </button>

          {/* Camera view area */}
          <div className="map-floating-panel__camera">
            <div className="map-floating-panel__camera-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
              <span>카메라 피드</span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="map-floating-panel__actions">
            <button
              className="map-floating-panel__btn map-floating-panel__btn--primary"
              onClick={onStartMapping}
              title="맵핑 시작"
            >
              맵핑 시작
            </button>
            <button
              className="map-floating-panel__btn map-floating-panel__btn--danger"
              onClick={onClearMap}
            >
              맵 초기화
            </button>
            <button
              className="map-floating-panel__btn"
              onClick={onRemoteImage}
              disabled={!robotConnected}
              title={!robotConnected ? "로봇을 먼저 연결하세요" : "원격 영상"}
            >
              원격 영상
            </button>
            <button
              className="map-floating-panel__btn"
              onClick={onRemoteControl}
              disabled={!robotConnected}
              title={!robotConnected ? "로봇을 먼저 연결하세요" : "원격 제어"}
            >
              원격 제어
            </button>
          </div>
        </div>
      ) : (
        <button
          className="map-floating-panel__toggle map-floating-panel__toggle--collapsed"
          onClick={onToggle}
          title="패널 열기"
        >
          ◂
        </button>
      )}
    </div>
  );
}
