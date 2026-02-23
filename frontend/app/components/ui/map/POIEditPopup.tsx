"use client";

import { useState } from "react";
import type { POIEditPopupProps, POIType } from "@/lib/types/map";

const poiTypes: { value: POIType; label: string }[] = [
  { value: "standby", label: "Standby Point" },
  { value: "charging", label: "Charging Pile" },
  { value: "waypoint", label: "WayPoint" },
];

export function POIEditPopup({
  poi,
  onUpdate,
  onDelete,
  onClose,
}: POIEditPopupProps) {
  const [name, setName] = useState(poi.name);
  const [type, setType] = useState<POIType>(poi.type);

  const handleConfirm = () => {
    onUpdate(poi.id, {
      name: name.trim() || poi.name,
      type,
    });
    onClose();
  };

  return (
    <div className="poi-edit-overlay" onClick={onClose}>
      <div className="poi-edit-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="poi-edit-panel__title">Edit POI</h3>

        <div className="poi-edit-panel__body">
          {/* Name */}
          <div className="poi-edit-panel__field">
            <label className="poi-edit-panel__label">Name</label>
            <input
              className="poi-edit-panel__input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          {/* Location (read-only) */}
          <div className="poi-edit-panel__field">
            <label className="poi-edit-panel__label">Location</label>
            <input
              className="poi-edit-panel__input poi-edit-panel__input--readonly"
              value={`${poi.x.toFixed(4)}, ${poi.y.toFixed(4)}`}
              readOnly
            />
          </div>

          {/* General Type of Points */}
          <div className="poi-edit-panel__section">
            <span className="poi-edit-panel__section-title">General Type of Points</span>
            <div className="poi-edit-panel__radio-group">
              {poiTypes.map((t) => (
                <label key={t.value} className="poi-edit-panel__radio">
                  <input
                    type="radio"
                    name="poiType"
                    value={t.value}
                    checked={type === t.value}
                    onChange={() => setType(t.value)}
                  />
                  <span>{t.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="poi-edit-panel__actions">
          <button
            className="poi-edit-panel__btn poi-edit-panel__btn--delete"
            onClick={() => onDelete(poi.id)}
          >
            Delete
          </button>
          <button
            className="poi-edit-panel__btn poi-edit-panel__btn--confirm"
            onClick={handleConfirm}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
