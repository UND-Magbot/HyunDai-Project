"use client";

import { useState, useMemo, useCallback } from "react";
import type { MenuPermissionItem } from "@/lib/types/settings";

interface MenuTreeProps {
  selectedUserName: string | null;
  permissions: MenuPermissionItem[];
  onPermissionsChange: (permissions: MenuPermissionItem[]) => void;
  onSave?: () => void;
  isSaving?: boolean;
  canSave?: boolean;
}

export function MenuTree({
  selectedUserName,
  permissions,
  onPermissionsChange,
  onSave,
  isSaving = false,
  canSave = false,
}: MenuTreeProps) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search) return permissions;
    const kw = search.toLowerCase();
    return permissions.filter((p) => p.menuLabel.toLowerCase().includes(kw));
  }, [permissions, search]);

  const allChecked = filtered.length > 0 && filtered.every((p) => p.isAllowed);
  const someChecked = filtered.some((p) => p.isAllowed) && !allChecked;

  const handleToggleAll = useCallback(() => {
    const targetKeys = new Set(filtered.map((p) => p.menuKey));
    const newValue = !allChecked;
    onPermissionsChange(
      permissions.map((p) =>
        targetKeys.has(p.menuKey) ? { ...p, isAllowed: newValue } : p
      )
    );
  }, [filtered, allChecked, permissions, onPermissionsChange]);

  const handleToggle = useCallback(
    (menuKey: string) => {
      onPermissionsChange(
        permissions.map((p) =>
          p.menuKey === menuKey ? { ...p, isAllowed: !p.isAllowed } : p
        )
      );
    },
    [permissions, onPermissionsChange]
  );

  if (!selectedUserName) {
    return (
      <div className="menu-tree">
        <p className="menu-tree__empty">사용자를 선택해주세요</p>
      </div>
    );
  }

  return (
    <div className="menu-tree">
      <div className="menu-tree__header">
        <h3 className="menu-tree__title">
          <span className="menu-tree__user-label">{selectedUserName}</span>
          메뉴 권한
        </h3>
        {onSave && (
          <button
            className="menu-tree__save-btn"
            disabled={!canSave || isSaving}
            onClick={onSave}
          >
            {isSaving ? "저장 중..." : "저장"}
          </button>
        )}
      </div>
      <input
        className="menu-tree__search"
        type="text"
        placeholder="메뉴 검색"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="menu-tree__list">
        <label className="menu-tree__item menu-tree__item--parent">
          <input
            type="checkbox"
            className="menu-tree__checkbox"
            checked={allChecked}
            ref={(el) => {
              if (el) el.indeterminate = someChecked;
            }}
            onChange={handleToggleAll}
          />
          <span>Full Menu</span>
        </label>
        {filtered.map((perm) => (
          <label key={perm.menuKey} className="menu-tree__item">
            <input
              type="checkbox"
              className="menu-tree__checkbox"
              checked={perm.isAllowed}
              onChange={() => handleToggle(perm.menuKey)}
            />
            <span>{perm.menuLabel}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
