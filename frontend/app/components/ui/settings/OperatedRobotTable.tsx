"use client";

import type { RobotDevice } from "@/lib/types/robots";
import "./OperatedRobotTable.css";

function PowerCell({ power }: { power: number | null }) {
  if (power == null) return <span className="operated-table__muted">-</span>;

  let className = "operated-table__power";
  if (power <= 10) {
    className += " operated-table__power--emergency";
  } else if (power <= 30) {
    className += " operated-table__power--danger";
  }

  return <span className={className}>{power}%</span>;
}

type OperatedRobotTableProps = {
  devices: RobotDevice[];
};

export function OperatedRobotTable({ devices }: OperatedRobotTableProps) {
  return (
    <div className="operated-table-wrapper">
      <table className="operated-table">
        <colgroup>
          <col />{/* Warning */}
          <col />{/* Name */}
          <col />{/* SN */}
          <col />{/* Online Status */}
          <col />{/* Current Battery */}
          <col />{/* Mission Status */}
          <col />{/* Operation */}
        </colgroup>
        <thead>
          <tr>
            <th></th>
            <th>Name</th>
            <th>SN</th>
            <th>Online Status</th>
            <th>Current Battery</th>
            <th>Mission Status</th>
            <th>Operation</th>
          </tr>
        </thead>
        <tbody>
          {devices.length === 0 ? (
            <tr>
              <td colSpan={7} className="operated-table__empty">
                No operated robots found
              </td>
            </tr>
          ) : (
            devices.map((device) => {
              const isOffline = !device.online;
              const rowClass = `operated-table__row${isOffline ? " operated-table__row--offline" : ""}`;

              return (
                <tr key={device.id} className={rowClass}>
                  <td>
                    {isOffline && (
                      <svg
                        className="operated-table__warning-icon"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="var(--color-warning)"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                        <line x1="12" y1="9" x2="12" y2="13" />
                        <line x1="12" y1="17" x2="12.01" y2="17" />
                      </svg>
                    )}
                  </td>
                  <td className="operated-table__name">{device.robotName}</td>
                  <td>{device.sn}</td>
                  <td>
                    <span
                      className={`operated-table__online operated-table__online--${device.online ? "on" : "off"}`}
                    >
                      {device.online ? "Online" : "Offline"}
                    </span>
                  </td>
                  <td>
                    <PowerCell power={device.power} />
                  </td>
                  <td>
                    <span className="operated-table__mission">
                      {device.runState ?? "Available"}
                    </span>
                  </td>
                  <td>
                    <div className="operated-table__actions">
                      <button
                        className="operated-table__action-btn"
                        disabled={isOffline}
                        title={isOffline ? "Robot is offline" : "Remote Desktop"}
                      >
                        Remote Desktop
                      </button>
                      <button
                        className="operated-table__action-btn"
                        disabled={isOffline}
                        title={isOffline ? "Robot is offline" : "Monitor"}
                      >
                        Monitor
                      </button>
                    </div>
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
