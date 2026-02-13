"use client";

import type { RobotDevice } from "@/lib/types/robots";
import "./SettingsRobotTable.css";

type SettingsRobotTableProps = {
  devices: RobotDevice[];
  onSettingsClick: (deviceId: string) => void;
  onDetailClick: (deviceId: string) => void;
};

export function SettingsRobotTable({
  devices,
  onSettingsClick,
  onDetailClick,
}: SettingsRobotTableProps) {
  return (
    <div className="settings-table-wrapper">
      <table className="settings-table">
        <colgroup>
          <col />{/* Name */}
          <col />{/* SN */}
          <col />{/* APK */}
          <col />{/* SDK */}
          <col />{/* Deployment Date */}
          <col />{/* Businesses */}
          <col />{/* Building */}
          <col />{/* Operation */}
        </colgroup>
        <thead>
          <tr>
            <th>Name</th>
            <th>SN</th>
            <th>APK</th>
            <th>SDK</th>
            <th>Deployment Date</th>
            <th>Businesses</th>
            <th>Building</th>
            <th>Operation</th>
          </tr>
        </thead>
        <tbody>
          {devices.length === 0 ? (
            <tr>
              <td colSpan={8} className="settings-table__empty">
                No devices found
              </td>
            </tr>
          ) : (
            devices.map((device) => (
              <tr key={device.id} className="settings-table__row">
                <td className="settings-table__name">{device.robotName}</td>
                <td>{device.sn}</td>
                <td>{device.apkVersion ?? <span className="settings-table__muted">-</span>}</td>
                <td>{device.sdkVersion ?? <span className="settings-table__muted">-</span>}</td>
                <td>
                  {device.deploymentTime ?? (
                    <span className="settings-table__muted">Undeployed</span>
                  )}
                </td>
                <td>{device.busiName ?? <span className="settings-table__muted">-</span>}</td>
                <td>{device.buildingName ?? <span className="settings-table__muted">-</span>}</td>
                <td>
                  <div className="settings-table__actions">
                    <button
                      className="settings-table__settings-btn"
                      onClick={() => onSettingsClick(device.id)}
                    >
                      Add Settings
                    </button>
                    <button
                      className="settings-table__detail-btn"
                      onClick={() => onDetailClick(device.id)}
                    >
                      Detail
                    </button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
