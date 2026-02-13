"use client";

import type { RobotTableProps } from "@/lib/types/robots";
import "./RobotTable.css";

function PowerCell({ power }: { power: number | null }) {
  if (power == null) return <span className="robot-table__muted">-</span>;

  const className =
    power <= 30 ? "robot-table__power robot-table__power--danger" : "robot-table__power";

  return <span className={className}>{power}%</span>;
}

export function RobotTable({
  devices,
  onEnableToggle,
  onInfoClick,
  togglingDeviceId,
}: RobotTableProps) {
  return (
    <div className="robot-table-wrapper">
      <table className="robot-table">
        <colgroup>
          <col />{/* SN */}
          <col />{/* RobotName */}
          <col />{/* Model */}
          <col />{/* RunState */}
          <col />{/* Online */}
          <col />{/* Signal */}
          <col />{/* Power */}
          <col />{/* Enable */}
          <col />{/* Operation */}
        </colgroup>
        <thead>
          <tr>
            <th>SN</th>
            <th>RobotName</th>
            <th>Model</th>
            <th>RunState</th>
            <th>Online</th>
            <th>Signal</th>
            <th>Power (%)</th>
            <th>Enable</th>
            <th>Operation</th>
          </tr>
        </thead>
        <tbody>
          {devices.length === 0 ? (
            <tr>
              <td colSpan={9} className="robot-table__empty">
                No devices found
              </td>
            </tr>
          ) : (
            devices.map((device) => {
              const rowClass = `robot-table__row${!device.online ? " robot-table__row--offline" : ""}`;

              let runStateClass = "robot-table__run-state";
              if (device.runState === "EXECUTING")
                runStateClass += " robot-table__run-state--executing";
              else if (device.runState === "CHARGING")
                runStateClass += " robot-table__run-state--charging";

              const isToggleDisabled = togglingDeviceId === device.id;

              return (
                <tr key={device.id} className={rowClass}>
                  <td>{device.sn}</td>
                  <td className="robot-table__name">{device.robotName}</td>
                  <td>{device.model}</td>
                  <td>
                    <span className={runStateClass}>
                      {device.runState ?? "-"}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`robot-table__online robot-table__online--${device.online ? "on" : "off"}`}
                    >
                      {device.online ? "Online" : "Offline"}
                    </span>
                  </td>
                  <td>
                    {device.signal != null ? (
                      `${device.signal} dBm`
                    ) : (
                      <span
                        className="robot-table__muted"
                        title="Signal data unavailable"
                      >
                        N/A
                      </span>
                    )}
                  </td>
                  <td>
                    <PowerCell power={device.power} />
                  </td>
                  <td>
                    <label className="robot-table__toggle">
                      <input
                        type="checkbox"
                        checked={device.enable}
                        onChange={() => onEnableToggle(device.id)}
                        disabled={isToggleDisabled}
                      />
                      <span className="robot-table__toggle-slider" />
                    </label>
                  </td>
                  <td>
                    <button
                      className="robot-table__info-btn"
                      onClick={() => onInfoClick(device.id)}
                    >
                      Info
                    </button>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
