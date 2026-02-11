"use client";

import type { LayerButtonProps } from "@/lib/types/monitoring";

export function LayerButton({ isActive, onToggle }: LayerButtonProps) {
  return (
    <button
      className={isActive ? "overlay-btn overlay-btn--active" : "overlay-btn"}
      onClick={onToggle}
    >
      LAYERS
    </button>
  );
}
