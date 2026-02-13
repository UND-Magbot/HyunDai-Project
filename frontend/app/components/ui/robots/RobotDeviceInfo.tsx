"use client";

import { Modal } from "../Modal";
import type { RobotDeviceInfoProps } from "@/lib/types/robots";
import "./RobotDeviceInfo.css";

function formatValue(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  return String(value);
}

export function RobotDeviceInfo({
  device,
  onClose,
  onEnableToggle,
  togglingDeviceId,
}: RobotDeviceInfoProps) {
  if (!device) return null;

  const isToggleDisabled = togglingDeviceId === device.id;

  const shouldScrollTaskTable = device.currentTask.length > 5;

  const renderPower = () => {
    if (device.power == null) return "-";

    return (
      <span className={`robot-info__power-value${device.power <= 30 ? " robot-info__power-value--danger" : ""}`}>
        {device.power}%
      </span>
    );
  };

  return (
    <Modal open onClose={onClose} title="Device Info" width="760px">
      <div className="robot-info">
        {/* Base Information */}
        <section className="robot-info__section">
          <h3 className="robot-info__section-title">Base Information</h3>
          <div className="robot-info__grid">
            <div className="robot-info__field">
              <span className="robot-info__label">SN</span>
              <span className="robot-info__value">
                {formatValue(device.sn)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Robot Name</span>
              <span className="robot-info__value">
                {formatValue(device.robotName)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Model</span>
              <span className="robot-info__value">
                {formatValue(device.model)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Deploy Time</span>
              <span className="robot-info__value">
                {formatValue(device.deploymentTime)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">APK Version</span>
              <span className="robot-info__value">
                {formatValue(device.apkVersion)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">SDK Version</span>
              <span className="robot-info__value">
                {formatValue(device.sdkVersion)}
              </span>
            </div>
          </div>
        </section>

        {/* Operational */}
        <section className="robot-info__section">
          <h3 className="robot-info__section-title">Operational</h3>
          <div className="robot-info__grid">
            <div className="robot-info__field">
              <span className="robot-info__label">BUSI Name</span>
              <span className="robot-info__value">
                {formatValue(device.busiName)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Online</span>
              <span
                className={`robot-info__value robot-info__value--${device.online ? "online" : "offline"}`}
              >
                {device.online ? "Online" : "Offline"}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Run State</span>
              <span className="robot-info__value">
                {formatValue(device.runState)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Power</span>
              <span className="robot-info__value">{renderPower()}</span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Signal</span>
              <span className="robot-info__value">
                {device.signal != null ? `${device.signal} dBm` : "-"}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Enable</span>
              <label className="robot-info__toggle">
                <input
                  type="checkbox"
                  checked={device.enable}
                  onChange={() => onEnableToggle(device.id)}
                  disabled={isToggleDisabled}
                />
                <span className="robot-info__toggle-slider" />
              </label>
            </div>
          </div>
        </section>

        {/* Current Task */}
        <section className="robot-info__section">
          <h3 className="robot-info__section-title">Current Task</h3>
          {device.currentTask.length === 0 ? (
            <div className="robot-info__empty">No active task</div>
          ) : (
            <div
              className={`robot-info__table-wrapper${shouldScrollTaskTable ? " robot-info__table-wrapper--scroll" : ""}`}
            >
              <table className="robot-info__table">
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
                  {device.currentTask.map((task, idx) => (
                    <tr key={`${task.taskId}-${idx}`}>
                      <td>{task.taskId}</td>
                      <td>
                        <span
                          className={`robot-info__task-state robot-info__task-state--${task.state}`}
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
      </div>
    </Modal>
  );
}
