"use client";

import type { CustomTasksTableProps } from "@/lib/types/custom-tasks";
import "./CustomTasksTable.css";

export function CustomTasksTable({
  tasks,
  onEdit,
  onDelete,
}: CustomTasksTableProps) {
  return (
    <div className="ct-table-wrapper">
      <table className="ct-table">
        <colgroup>
          <col />
          <col />
          <col />
          <col />
        </colgroup>
        <thead>
          <tr>
            <th>TaskName</th>
            <th>Business</th>
            <th>CreateTime</th>
            <th>Operation</th>
          </tr>
        </thead>
        <tbody>
          {tasks.length === 0 ? (
            <tr>
              <td colSpan={4} className="ct-table__empty">
                No custom tasks found
              </td>
            </tr>
          ) : (
            tasks.map((task) => (
              <tr key={task.id} className="ct-table__row">
                <td className="ct-table__name">{task.taskName}</td>
                <td>{task.business}</td>
                <td>{task.createTime}</td>
                <td>
                  <div className="ct-table__actions">
                    <button
                      className="ct-table__edit-btn"
                      onClick={() => onEdit(task.id)}
                    >
                      Edit
                    </button>
                    <button
                      className="ct-table__delete-btn"
                      onClick={() => onDelete(task.id)}
                    >
                      Delete
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
