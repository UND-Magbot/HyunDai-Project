"use client";

import { useState, useMemo, useCallback, useRef } from "react";
import type { MenuPermissionItem } from "@/lib/types/settings";

interface MenuTreeProps {
  selectedUserName: string | null;
  permissions: MenuPermissionItem[];
  onPermissionsChange: (permissions: MenuPermissionItem[]) => void;
  onSave?: () => void;
  isSaving?: boolean;
  canSave?: boolean;
}

function IndeterminateCheckbox({
  checked,
  indeterminate,
  onChange,
  className,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
  className?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  if (ref.current) ref.current.indeterminate = indeterminate;
  return (
    <input
      ref={ref}
      type="checkbox"
      className={className}
      checked={checked}
      onChange={onChange}
    />
  );
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

  // menuId → 자식 항목 맵
  const childrenMap = useMemo(() => {
    const map: Record<number, MenuPermissionItem[]> = {};
    for (const p of permissions) {
      if (p.parentId) {
        if (!map[p.parentId]) map[p.parentId] = [];
        map[p.parentId].push(p);
      }
    }
    return map;
  }, [permissions]);

  // Full Menu 체크박스 상태 (자식 포함 전체 기준)
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

  // 부모 클릭: 자식이 있으면 자식 전체 토글, 없으면 자신 토글
  const handleToggleParent = useCallback(
    (perm: MenuPermissionItem) => {
      const children = perm.menuId ? (childrenMap[perm.menuId] ?? []) : [];
      if (children.length === 0) {
        onPermissionsChange(
          permissions.map((p) =>
            p.menuKey === perm.menuKey ? { ...p, isAllowed: !p.isAllowed } : p
          )
        );
        return;
      }
      const allChildrenChecked = children.every((c) => c.isAllowed);
      const newValue = !allChildrenChecked;
      const childKeys = new Set(children.map((c) => c.menuKey));
      onPermissionsChange(
        permissions.map((p) =>
          childKeys.has(p.menuKey) ? { ...p, isAllowed: newValue } : p
        )
      );
    },
    [childrenMap, permissions, onPermissionsChange]
  );

  // 자식 클릭: 자신만 토글
  const handleToggleChild = useCallback(
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

  const topLevel = filtered.filter((p) => !p.parentId);
  const filteredChildKeys = new Set(
    filtered.filter((p) => !!p.parentId).map((p) => p.menuKey)
  );

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
        {topLevel.map((perm) => {
          const children = perm.menuId
            ? (childrenMap[perm.menuId] ?? []).filter((c) =>
                filteredChildKeys.has(c.menuKey)
              )
            : [];
          const allChildrenChecked =
            children.length > 0 && children.every((c) => c.isAllowed);
          const someChildrenChecked =
            children.length > 0 &&
            children.some((c) => c.isAllowed) &&
            !allChildrenChecked;
          const displayChecked =
            children.length > 0 ? allChildrenChecked : perm.isAllowed;

          return (
            <div key={perm.menuKey}>
              <label className="menu-tree__item">
                <IndeterminateCheckbox
                  className="menu-tree__checkbox"
                  checked={displayChecked}
                  indeterminate={someChildrenChecked}
                  onChange={() => handleToggleParent(perm)}
                />
                <span>{perm.menuLabel}</span>
              </label>
              {children.map((child) => (
                <label
                  key={child.menuKey}
                  className="menu-tree__item menu-tree__item--child"
                >
                  <input
                    type="checkbox"
                    className="menu-tree__checkbox"
                    checked={child.isAllowed}
                    onChange={() => handleToggleChild(child.menuKey)}
                  />
                  <span>{child.menuLabel}</span>
                </label>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
