"use client";

import type { LogItem } from "@/lib/types/logs";
import "./LogTable.css";

type LogTableProps = {
  logs: LogItem[];
};

function val(v: string | null): string {
  return v ?? "-";
}

export function LogTable({ logs }: LogTableProps) {
  return (
    <div className="log-table__wrapper">
      <table className="log-table">
        <colgroup>
          <col style={{ width: "12%" }} />
          <col style={{ width: "22%" }} />
          <col style={{ width: "7%" }} />
          <col style={{ width: "7%" }} />
          <col style={{ width: "11%" }} />
          <col style={{ width: "8%" }} />
          <col style={{ width: "22%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>Time</th>
            <th>Message</th>
            <th>User</th>
            <th>Level</th>
            <th>Tag</th>
            <th>Type</th>
            <th>Data</th>
          </tr>
        </thead>
        <tbody>
          {logs.length === 0 ? (
            <tr>
              <td colSpan={7} className="log-table__empty">
                조회된 로그가 없습니다.
              </td>
            </tr>
          ) : (
            logs.map((log) => (
              <tr
                key={log.id}
                className={`log-table__row${log.level === "Error" ? " log-table__row--error" : ""}`}
              >
                <td>{log.time}</td>
                <td className="log-table__message" title={log.message}>
                  {log.message}
                </td>
                <td>{log.user}</td>
                <td>
                  <span
                    className={`log-table__level log-table__level--${log.level.toLowerCase()}`}
                  >
                    {log.level}
                  </span>
                </td>
                <td>{log.tag}</td>
                <td>{log.type}</td>
                <td className="log-table__data" title={val(log.data)}>
                  {val(log.data)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
