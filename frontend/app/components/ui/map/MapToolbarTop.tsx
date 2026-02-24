"use client";

import type { MapToolbarTopProps } from "@/lib/types/map";

const toolbarItems = [
  { key: "undo", icon: "↩", label: "되돌리기" },
  { key: "edit", icon: "✎", label: "편집" },
  { key: "charging", icon: "⚡", label: "충전소" },
  { key: "location", icon: "◎", label: "현재 위치" },
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
        title={isFullscreen ? "전체화면 해제" : "전체화면"}
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
