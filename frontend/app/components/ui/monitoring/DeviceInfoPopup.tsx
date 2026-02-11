"use client";

import { useMemo, useState } from "react";
import { Modal } from "../Modal";
import { getMockDeviceDetail } from "@/lib/mock/deviceDetails";
import type {
  DeviceDetail,
  DeviceInfoPopupProps,
} from "@/lib/types/monitoring";
import "./DeviceInfoPopup.css";

function formatValue(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  return String(value);
}

export function DeviceInfoPopup({ deviceId, onClose }: DeviceInfoPopupProps) {
  const initialDevice = useMemo(
    () => (deviceId ? getMockDeviceDetail(deviceId) : null),
    [deviceId]
  );

  const [device, setDevice] = useState<DeviceDetail | null>(initialDevice);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isTogglingEnable, setIsTogglingEnable] = useState(false);

  // Sync device state when deviceId changes
  if (initialDevice !== device && !isTogglingEnable) {
    setDevice(initialDevice);
    setErrorMessage(null);
  }

  const handleEnableToggle = () => {
    if (!device || isTogglingEnable) return;

    const previousValue = device.enable;
    setIsTogglingEnable(true);
    setErrorMessage(null);

    // Optimistic update
    setDevice({ ...device, enable: !previousValue });

    // Mock: simulate API
    setTimeout(() => {
      setIsTogglingEnable(false);
      // Production:
      // apiPatch(`/api/device/${deviceId}/enable`, { enable: !previousValue })
      //   .then(() => setIsTogglingEnable(false))
      //   .catch(() => {
      //     setDevice((prev) => prev ? { ...prev, enable: previousValue } : prev);
      //     setErrorMessage("Failed to update enable state");
      //     setIsTogglingEnable(false);
      //   });
    }, 300);
  };

  const renderContent = () => {
    if (!device) {
      return (
        <div className="device-info__error">
          <p>{errorMessage ?? "Device not found"}</p>
        </div>
      );
    }

    return (
      <div className="device-info">
        {/* Base Information */}
        <section className="device-info__section">
          <h3 className="device-info__section-title">Base Information</h3>
          <div className="device-info__grid">
            <div className="device-info__field">
              <span className="device-info__label">SN</span>
              <span className="device-info__value">
                {formatValue(device.sn)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Robot Name</span>
              <span className="device-info__value">
                {formatValue(device.robotName)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Model</span>
              <span className="device-info__value">
                {formatValue(device.model)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Deployment Time</span>
              <span className="device-info__value">
                {formatValue(device.deploymentTime)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">APK Version</span>
              <span className="device-info__value">
                {formatValue(device.apkVersion)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">SDK Version</span>
              <span className="device-info__value">
                {formatValue(device.sdkVersion)}
              </span>
            </div>
          </div>
        </section>

        {/* Operational */}
        <section className="device-info__section">
          <h3 className="device-info__section-title">Operational</h3>
          <div className="device-info__grid">
            <div className="device-info__field">
              <span className="device-info__label">BUSI Name</span>
              <span className="device-info__value">
                {formatValue(device.busiName)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Online</span>
              <span
                className={`device-info__value device-info__value--${device.online ? "online" : "offline"}`}
              >
                {device.online ? "Online" : "Offline"}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Run State</span>
              <span className="device-info__value">
                {formatValue(device.runState)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Power</span>
              <span className="device-info__value">
                {device.power != null ? `${device.power}%` : "-"}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Signal</span>
              <span className="device-info__value">
                {device.signal != null ? `${device.signal} dBm` : "-"}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Enable</span>
              <label className="device-info__toggle">
                <input
                  type="checkbox"
                  checked={device.enable}
                  onChange={handleEnableToggle}
                  disabled={isTogglingEnable}
                />
                <span className="device-info__toggle-slider" />
              </label>
            </div>
          </div>
        </section>

        {/* Current Task */}
        <section className="device-info__section">
          <h3 className="device-info__section-title">Current Task</h3>
          {device.currentTask.length === 0 ? (
            <div className="device-info__empty">No task data</div>
          ) : (
            <div className="device-info__table-wrapper">
              <table className="device-info__table">
                <thead>
                  <tr>
                    <th>Task ID</th>
                    <th>State</th>
                    <th>Type</th>
                    <th>Create Time</th>
                    <th>Start</th>
                    <th>End</th>
                    <th>Oper</th>
                  </tr>
                </thead>
                <tbody>
                  {device.currentTask.map((task) => (
                    <tr key={task.taskId}>
                      <td>{task.taskId}</td>
                      <td>
                        <span
                          className={`device-info__task-state device-info__task-state--${task.state}`}
                        >
                          {task.state}
                        </span>
                      </td>
                      <td>{task.type}</td>
                      <td>{task.createTime}</td>
                      <td>{task.start}</td>
                      <td>{task.end}</td>
                      <td>{task.oper}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {errorMessage && (
          <div className="device-info__inline-error">{errorMessage}</div>
        )}
      </div>
    );
  };

  return (
    <Modal
      open={!!deviceId}
      onClose={onClose}
      title="Device Info"
      width="760px"
    >
      {renderContent()}
    </Modal>
  );
}
