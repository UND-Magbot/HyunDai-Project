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
            title="Close panel"
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
              <span>Camera Feed</span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="map-floating-panel__actions">
            <button
              className="map-floating-panel__btn map-floating-panel__btn--primary"
              onClick={onStartMapping}
              title="Start Mapping"
            >
              Start Mapping
            </button>
            <button
              className="map-floating-panel__btn map-floating-panel__btn--danger"
              onClick={onClearMap}
            >
              Clear The Map
            </button>
            <button
              className="map-floating-panel__btn"
              onClick={onRemoteImage}
              disabled={!robotConnected}
              title={!robotConnected ? "Connect a robot first" : "Remote Image"}
            >
              Remote Image
            </button>
            <button
              className="map-floating-panel__btn"
              onClick={onRemoteControl}
              disabled={!robotConnected}
              title={!robotConnected ? "Connect a robot first" : "Remote Control"}
            >
              Remote Control
            </button>
          </div>
        </div>
      ) : (
        <button
          className="map-floating-panel__toggle map-floating-panel__toggle--collapsed"
          onClick={onToggle}
          title="Open panel"
        >
          ◂
        </button>
      )}
    </div>
  );
}
