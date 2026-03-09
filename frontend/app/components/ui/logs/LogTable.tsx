"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LogItem } from "@/lib/types/logs";
import { Modal } from "@/app/components/ui/Modal";
import "./LogTable.css";

type LogTableProps = {
  logs: LogItem[];
};

function formatData(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export function LogTable({ logs }: LogTableProps) {
  const [viewData, setViewData] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [overflowIds, setOverflowIds] = useState<Set<string>>(new Set());
  const msgRefs = useRef<Map<string, HTMLElement>>(new Map());

  const checkOverflows = useCallback(() => {
    const next = new Set<string>();
    msgRefs.current.forEach((el, id) => {
      if (el.scrollHeight > el.clientHeight) next.add(id);
    });
    setOverflowIds(next);
  }, []);

  useEffect(() => {
    checkOverflows();
  }, [logs, checkOverflows]);

  const handleRowClick = (id: string) => {
    if (!overflowIds.has(id)) return;
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <>
      <div className="log-table__wrapper">
        <table className="log-table">
          <colgroup>
            <col style={{ width: "15%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "13%" }} />
            <col style={{ width: "50%" }} />
            <col style={{ width: "8%" }} />
          </colgroup>
          <thead>
            <tr>
              <th>발생 일시</th>
              <th>오류 타입</th>
              <th>IP</th>
              <th>메세지</th>
              <th>데이터</th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 ? (
              <tr>
                <td colSpan={5} className="log-table__empty">
                  조회된 로그가 없습니다.
                </td>
              </tr>
            ) : (
              logs.map((log) => {
                const isOverflow = overflowIds.has(log.id);
                const isExpanded = expandedId === log.id;

                return (
                  <tr
                    key={log.id}
                    className={`log-table__row${isOverflow ? " log-table__row--expandable" : ""}`}
                    onClick={() => handleRowClick(log.id)}
                  >
                    <td>{log.time}</td>
                    <td>
                      <span
                        className={`log-table__error-type log-table__error-type--${log.errorType}`}
                      >
                        {log.errorType}
                      </span>
                    </td>
                    <td>{log.ip}</td>
                    <td className="log-table__message-cell">
                      <div
                        className={`log-table__message${isExpanded ? " log-table__message--expanded" : ""}`}
                        ref={(el) => {
                          if (el) msgRefs.current.set(log.id, el);
                          else msgRefs.current.delete(log.id);
                        }}
                      >
                        {log.message}
                      </div>
                    </td>
                    <td>
                      {log.data ? (
                        <button
                          className="log-table__view-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setViewData(log.data);
                          }}
                        >
                          View
                        </button>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <Modal
        open={viewData !== null}
        onClose={() => setViewData(null)}
        title="Data"
        width="520px"
      >
        <div className="log-table__json-viewer">
          <pre>{viewData ? formatData(viewData) : ""}</pre>
        </div>
      </Modal>
    </>
  );
}
