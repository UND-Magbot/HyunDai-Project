"use client";

import type { ConnectedRobot } from "@/lib/types/map";

type BusinessItem = {
  business_id: number;
  name: string;
};

type AreaItem = {
  area_id: number;
  name: string;
};

type MapTopBarProps = {
  connectedRobot: ConnectedRobot;
  onConnectClick: () => void;
  businesses: BusinessItem[];
  selectedBusiness: string;
  onBusinessChange: (value: string) => void;
  areas: AreaItem[];
  selectedArea: string;
  onAreaChange: (value: string) => void;
  onSave: () => void;
  onSync: () => void;
  onCreate: () => void;
  onDelete: () => void;
};

export function MapTopBar({
  connectedRobot,
  onConnectClick,
  businesses,
  selectedBusiness,
  onBusinessChange,
  areas,
  selectedArea,
  onAreaChange,
  onSave,
  onSync,
  onCreate,
  onDelete,
}: MapTopBarProps) {
  return (
    <>
      <div className="map-top-bar">
        <div className="map-top-bar__left">
          <label>
            <span className="map-selector-row__label">사업장: </span>
            <select
              className="map-top-bar__dropdown"
              value={selectedBusiness}
              onChange={(e) => onBusinessChange(e.target.value)}
            >
              <option value="">사업장 선택</option>
              {businesses.map((b) => (
                <option key={b.business_id} value={String(b.business_id)}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="map-selector-row__label">영역: </span>
            <select
              className="map-top-bar__dropdown"
              value={selectedArea}
              onChange={(e) => onAreaChange(e.target.value)}
            >
              <option value="">영역 선택</option>
              {areas.map((a) => (
                <option key={a.area_id} value={String(a.area_id)}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="map-top-bar__center">
          <button className="map-top-bar__btn" onClick={onSave}>저장</button>
          <button className="map-top-bar__btn" onClick={onSync} disabled>동기화</button>
          <button className="map-top-bar__btn" onClick={onCreate}>생성</button>
          <button className="map-top-bar__btn" onClick={onDelete}>삭제</button>
        </div>

        <div className="map-top-bar__right">
          {connectedRobot ? (
            <button
              className="map-top-bar__btn map-top-bar__btn--connected"
              onClick={onConnectClick}
            >
              🤖 {connectedRobot.name}
            </button>
          ) : (
            <button
              className="map-top-bar__btn map-top-bar__btn--connect"
              onClick={onConnectClick}
            >
              로봇 연결
            </button>
          )}
        </div>
      </div>
    </>
  );
}
