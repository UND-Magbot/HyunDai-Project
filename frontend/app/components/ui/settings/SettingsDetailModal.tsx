"use client";

import { Modal } from "../Modal";
import type { SettingsDetailModalProps } from "@/lib/types/robots";
import "./SettingsDetailModal.css";

function formatValue(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  return String(value);
}

export function SettingsDetailModal({
  device,
  open,
  onClose,
}: SettingsDetailModalProps) {
  if (!device) return null;

  const renderPower = () => {
    if (device.power == null) return "-";
    let className = "settings-detail__power-value";
    if (device.power <= 10) {
      className += " settings-detail__power-value--emergency";
    } else if (device.power <= 30) {
      className += " settings-detail__power-value--danger";
    }
    return <span className={className}>{device.power}%</span>;
  };

  return (
    <Modal open={open} onClose={onClose} title="Device Detail" width="760px">
      <div className="settings-detail">
        {/* Base Information */}
        <section className="settings-detail__section">
          <h3 className="settings-detail__section-title">Base Information</h3>
          <div className="settings-detail__grid">
            <div className="settings-detail__field">
              <span className="settings-detail__label">Name</span>
              <span className="settings-detail__value">
                {formatValue(device.robotName)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">SN</span>
              <span className="settings-detail__value">
                {formatValue(device.sn)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Model</span>
              <span className="settings-detail__value">
                {formatValue(device.model)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">APK Version</span>
              <span className="settings-detail__value">
                {formatValue(device.apkVersion)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">SDK Version</span>
              <span className="settings-detail__value">
                {formatValue(device.sdkVersion)}
              </span>
            </div>
          </div>
        </section>

        {/* Deployment Information */}
        <section className="settings-detail__section">
          <h3 className="settings-detail__section-title">Deployment</h3>
          <div className="settings-detail__grid">
            <div className="settings-detail__field">
              <span className="settings-detail__label">Deployment Date</span>
              <span className="settings-detail__value">
                {formatValue(device.deploymentTime)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Businesses</span>
              <span className="settings-detail__value">
                {formatValue(device.busiName)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Building</span>
              <span className="settings-detail__value">
                {formatValue(device.buildingName)}
              </span>
            </div>
          </div>
        </section>

        {/* Operational */}
        <section className="settings-detail__section">
          <h3 className="settings-detail__section-title">Operational</h3>
          <div className="settings-detail__grid">
            <div className="settings-detail__field">
              <span className="settings-detail__label">Online</span>
              <span
                className={`settings-detail__value settings-detail__value--${device.online ? "online" : "offline"}`}
              >
                {device.online ? "Online" : "Offline"}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Power</span>
              <span className="settings-detail__value">{renderPower()}</span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Signal</span>
              <span className="settings-detail__value">
                {device.signal != null ? `${device.signal} dBm` : "-"}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Run State</span>
              <span className="settings-detail__value">
                {formatValue(device.runState)}
              </span>
            </div>
            <div className="settings-detail__field">
              <span className="settings-detail__label">Enable</span>
              <span className="settings-detail__value">
                {device.enable ? "Enabled" : "Disabled"}
              </span>
            </div>
          </div>
        </section>
      </div>
    </Modal>
  );
}
