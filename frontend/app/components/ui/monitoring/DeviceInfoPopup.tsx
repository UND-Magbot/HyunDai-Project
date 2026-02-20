"use client";

import { useRef, useState } from "react";
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
  const prevDeviceIdRef = useRef(deviceId);
  const [device, setDevice] = useState<DeviceDetail | null>(
    deviceId ? getMockDeviceDetail(deviceId) : null
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isTogglingEnable, setIsTogglingEnable] = useState(false);

  // Sync device state only when deviceId actually changes
  if (prevDeviceIdRef.current !== deviceId) {
    prevDeviceIdRef.current = deviceId;
    setDevice(deviceId ? getMockDeviceDetail(deviceId) : null);
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

    const shouldScrollTaskTable = device.currentTask.length > 5;

    return (
      <div className="device-info">
        {/* Base Information */}
        <section className="device-info__section">
          <h3 className="device-info__section-title">기본 정보</h3>
          <div className="device-info__grid">
            <div className="device-info__field">
              <span className="device-info__label">SN</span>
              <span className="device-info__value">
                {formatValue(device.sn)}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">로봇 명</span>
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
              <span className="device-info__label">Deploy Time</span>
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
              <span className="device-info__label">전원</span>
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
              <span className="device-info__label">배터리</span>
              <span className="device-info__value">
                {device.power != null ? `${device.power}%` : "-"}
              </span>
            </div>
            <div className="device-info__field">
              <span className="device-info__label">Signal</span>
              <span className="device-info__value">
                {device.signal != null ? `${device.signal} %` : "-"}
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
          <h3 className="device-info__section-title">현재 작업</h3>
          {device.currentTask.length === 0 ? (
            <div className="device-info__empty">작업 데이터가 없습니다.</div>
          ) : (
            <div
              className={`device-info__table-wrapper${shouldScrollTaskTable ? " device-info__table-wrapper--scroll" : ""}`}
            >
              <table className="device-info__table">
                <thead>
                  <tr>
                    <th>작업 ID</th>
                    <th>상태</th>
                    <th>유형</th>
                    <th>등록일</th>
                    <th>시작 지점</th>
                    <th>종료 지점</th>
                    <th>담당자</th>
                  </tr>
                </thead>
                <tbody>
                  {device.currentTask.map((task, idx) => (
                    <tr key={`${task.taskId}-${idx}`}>
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
