"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { Modal } from "../Modal";
import { mockBusinesses, mockBuildings } from "@/lib/mock/robotDevices";
import type { RobotSettingsModalProps } from "@/lib/types/robots";
import "./RobotSettingsModal.css";

function formatValue(value: string | null | undefined): string {
  if (value == null || value === "") return "-";
  return value;
}

function todayString(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function RobotSettingsModal({
  device,
  open,
  onClose,
  onSave,
}: RobotSettingsModalProps) {
  const [businessId, setBusinessId] = useState("");
  const [buildingId, setBuildingId] = useState("");
  const [deploymentDate, setDeploymentDate] = useState(todayString);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (device && open) {
      setBusinessId("");
      setBuildingId("");
      setDeploymentDate(device.deploymentTime ?? todayString());
      setErrors({});
    }
  }, [device, open]);

  const filteredBuildings = useMemo(
    () => mockBuildings.filter((b) => b.businessId === businessId),
    [businessId]
  );

  const handleBusinessChange = useCallback((value: string) => {
    setBusinessId(value);
    setBuildingId("");
    setErrors((prev) => {
      const next = { ...prev };
      delete next.businessId;
      delete next.buildingId;
      return next;
    });
  }, []);

  const handleBuildingChange = useCallback((value: string) => {
    setBuildingId(value);
    setErrors((prev) => {
      const next = { ...prev };
      delete next.buildingId;
      return next;
    });
  }, []);

  const handleClose = useCallback(() => {
    setErrors({});
    onClose();
  }, [onClose]);

  const handleSave = useCallback(() => {
    if (!device) return;

    const newErrors: Record<string, string> = {};
    if (!businessId) {
      newErrors.businessId = "Business is required";
    }
    if (!buildingId) {
      newErrors.buildingId = "Building is required";
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    onSave(device.id, {
      businessId,
      buildingId,
      deploymentDate,
      status: "DEPLOYED",
    });
    onClose();
  }, [device, businessId, buildingId, deploymentDate, onSave, onClose]);

  if (!device) return null;

  const currentStatus = device.busiName ? "DEPLOYED" : "UNDEPLOYED";

  return (
    <Modal open={open} onClose={handleClose} title="Robot Settings" width="560px">
      <div className="robot-settings">
        {/* Basic Information (Readonly) */}
        <section className="robot-settings__section">
          <h3 className="robot-settings__section-title">Basic Information</h3>
          <div className="robot-settings__grid">
            <div className="robot-settings__readonly-field">
              <span className="robot-settings__readonly-label">Name</span>
              <span className="robot-settings__readonly-value">
                {formatValue(device.robotName)}
              </span>
            </div>
            <div className="robot-settings__readonly-field">
              <span className="robot-settings__readonly-label">SN</span>
              <span className="robot-settings__readonly-value">
                {formatValue(device.sn)}
              </span>
            </div>
            <div className="robot-settings__readonly-field">
              <span className="robot-settings__readonly-label">APK</span>
              <span className="robot-settings__readonly-value">
                {formatValue(device.apkVersion)}
              </span>
            </div>
            <div className="robot-settings__readonly-field">
              <span className="robot-settings__readonly-label">SDK</span>
              <span className="robot-settings__readonly-value">
                {formatValue(device.sdkVersion)}
              </span>
            </div>
          </div>
        </section>

        {/* Deployment Settings */}
        <section className="robot-settings__section">
          <h3 className="robot-settings__section-title">Deployment Settings</h3>
          <div className="robot-settings__form">
            {/* Business */}
            <div className="robot-settings__field">
              <span className="robot-settings__label">
                Business <span className="robot-settings__required">*</span>
              </span>
              <select
                className={`robot-settings__select${!businessId ? " robot-settings__select--placeholder" : ""}${errors.businessId ? " robot-settings__select--error" : ""}`}
                value={businessId}
                onChange={(e) => handleBusinessChange(e.target.value)}
              >
                <option value="" disabled hidden>
                  Select Business
                </option>
                {mockBusinesses.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              {errors.businessId && (
                <span className="robot-settings__error">{errors.businessId}</span>
              )}
            </div>

            {/* Building */}
            <div className="robot-settings__field">
              <span className="robot-settings__label">
                Building <span className="robot-settings__required">*</span>
              </span>
              <select
                className={`robot-settings__select${!buildingId ? " robot-settings__select--placeholder" : ""}${errors.buildingId ? " robot-settings__select--error" : ""}`}
                value={buildingId}
                onChange={(e) => handleBuildingChange(e.target.value)}
                disabled={!businessId}
              >
                <option value="" disabled hidden>
                  {businessId ? "Select Building" : "Select Business first"}
                </option>
                {filteredBuildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              {errors.buildingId && (
                <span className="robot-settings__error">{errors.buildingId}</span>
              )}
            </div>

            {/* Deployment Date */}
            <div className="robot-settings__field">
              <span className="robot-settings__label">Deployment Date</span>
              <input
                type="date"
                className="robot-settings__date-input"
                value={deploymentDate}
                onChange={(e) => setDeploymentDate(e.target.value)}
              />
            </div>

            {/* Deployment Status */}
            <div className="robot-settings__field">
              <span className="robot-settings__label">Deployment Status</span>
              <span
                className={`robot-settings__status-badge robot-settings__status-badge--${currentStatus === "DEPLOYED" ? "deployed" : "undeployed"}`}
              >
                {currentStatus === "DEPLOYED" ? "Deployed" : "Undeployed"}
              </span>
            </div>
          </div>
        </section>

        {/* Footer */}
        <div className="robot-settings__footer">
          <button
            type="button"
            className="robot-settings__btn robot-settings__btn--cancel"
            onClick={handleClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="robot-settings__btn robot-settings__btn--save"
            onClick={handleSave}
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
