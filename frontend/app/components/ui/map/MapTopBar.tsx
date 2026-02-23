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
            <span className="map-selector-row__label">Business: </span>
            <select
              className="map-top-bar__dropdown"
              value={selectedBusiness}
              onChange={(e) => onBusinessChange(e.target.value)}
            >
              <option value="">Select Business</option>
              {businesses.map((b) => (
                <option key={b.business_id} value={String(b.business_id)}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="map-selector-row__label">Area: </span>
            <select
              className="map-top-bar__dropdown"
              value={selectedArea}
              onChange={(e) => onAreaChange(e.target.value)}
            >
              <option value="">Select Area</option>
              {areas.map((a) => (
                <option key={a.area_id} value={String(a.area_id)}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="map-top-bar__center">
          <button className="map-top-bar__btn" onClick={onSave}>Save</button>
          <button className="map-top-bar__btn" onClick={onSync}>Sync</button>
          <button className="map-top-bar__btn" onClick={onCreate}>Create</button>
          <button className="map-top-bar__btn" onClick={onDelete}>Delete</button>
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
              GO TO CONNECT
            </button>
          )}
        </div>
      </div>
    </>
  );
}
