"use client";

import type { MapToolbarTopProps } from "@/lib/types/map";

const toolbarItems = [
  { key: "undo", icon: "↩", label: "Undo" },
  { key: "absorb", icon: "⊕", label: "Absorb" },
  { key: "edit", icon: "✎", label: "Edit" },
  { key: "angle", icon: "∠", label: "Angle" },
  { key: "charging", icon: "⚡", label: "Charging Pile" },
  { key: "location", icon: "◎", label: "Current Location" },
];

export function MapToolbarTop({
  onUndo,
  onFullscreen,
  isFullscreen,
  onChargingPile,
  onCurrentPos,
}: MapToolbarTopProps) {
  const handleClick = (key: string) => {
    switch (key) {
      case "undo": return onUndo();
      case "charging": return onChargingPile();
      case "location": return onCurrentPos();
    }
  };

  return (
    <>
      <button
        className="map-toolbar-top__fullscreen"
        onClick={onFullscreen}
        title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
      >
        {isFullscreen ? "⊡" : "⊞"}
      </button>

      <div className="map-toolbar-top">
        <div className="map-toolbar-top__bar">
          {toolbarItems.map((item) => (
            <button
              key={item.key}
              className="map-toolbar-top__item"
              onClick={() => handleClick(item.key)}
              title={item.label}
            >
              <span className="map-toolbar-top__item-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
