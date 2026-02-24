"use client";

import type { LineDirectionPopupProps } from "@/lib/types/map";

export function LineDirectionPopup({
  position,
  onSelect,
  onCancel,
}: LineDirectionPopupProps) {
  return (
    <div
      className="line-direction-popup"
      style={{ left: position.x, top: position.y }}
    >
      <div className="line-direction-popup__title">Select Direction</div>
      <button
        className="line-direction-popup__option"
        onClick={() => onSelect("forward")}
      >
        <span className="line-direction-popup__option-icon">→</span>
        A → B (Forward)
      </button>
      <button
        className="line-direction-popup__option"
        onClick={() => onSelect("backward")}
      >
        <span className="line-direction-popup__option-icon">←</span>
        B → A (Backward)
      </button>
      <button
        className="line-direction-popup__option"
        onClick={() => onSelect("bidirectional")}
      >
        <span className="line-direction-popup__option-icon">↔</span>
        A ↔ B (Bidirectional)
      </button>
      <button className="line-direction-popup__cancel" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
