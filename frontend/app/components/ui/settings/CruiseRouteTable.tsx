"use client";

import type { CruiseRouteTableProps } from "@/lib/types/cruise-route";
import "./CruiseRouteTable.css";

export function CruiseRouteTable({
  routes,
  onEdit,
  onDelete,
}: CruiseRouteTableProps) {
  return (
    <div className="cr-table-wrapper">
      <table className="cr-table">
        <colgroup>
          <col />
          <col />
          <col />
          <col />
          <col />
        </colgroup>
        <thead>
          <tr>
            <th>Route Name</th>
            <th>Businesses</th>
            <th>Number of sites</th>
            <th>Creation Time</th>
            <th>Operation</th>
          </tr>
        </thead>
        <tbody>
          {routes.length === 0 ? (
            <tr>
              <td colSpan={5} className="cr-table__empty">
                No cruise routes found
              </td>
            </tr>
          ) : (
            routes.map((route) => (
              <tr key={route.id} className="cr-table__row">
                <td className="cr-table__name">{route.routeName}</td>
                <td>{route.businessName}</td>
                <td>{route.siteCount}</td>
                <td>{route.createTime}</td>
                <td>
                  <div className="cr-table__actions">
                    <button
                      className="cr-table__edit-btn"
                      onClick={() => onEdit(route.id)}
                    >
                      Edit
                    </button>
                    <button
                      className="cr-table__delete-btn"
                      onClick={() => onDelete(route.id)}
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
