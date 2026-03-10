"use client";

import { useState, useCallback, useEffect } from "react";
import { useAlert } from "@/lib/context/AlertContext";
import { PersonTree } from "./PersonTree";
import { MenuTree } from "./MenuTree";
import {
  fetchUsers,
  getMenuPermissions,
  saveMenuPermissions as apiSavePermissions,
  downloadDbBackup,
} from "@/lib/api/settings";
import type {
  BusinessGroup,
  BusinessUser,
  MenuPermissionItem,
} from "@/lib/types/settings";
import "./MenuPermissionTab.css";

export function MenuPermissionTab() {
  const { showInfo } = useAlert();
  const [groups, setGroups] = useState<BusinessGroup[]>([]);
  const [selectedUser, setSelectedUser] = useState<BusinessUser | null>(null);
  const [permissions, setPermissions] = useState<MenuPermissionItem[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isBackingUp, setIsBackingUp] = useState(false);

  useEffect(() => {
    fetchUsers().then(setGroups).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedUser) return;
    getMenuPermissions(selectedUser.id).then(setPermissions);
  }, [selectedUser]);

  const handleSelectUser = useCallback((user: BusinessUser) => {
    setSelectedUser(user);
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedUser) return;
    if (!permissions.some((p) => p.isAllowed)) {
      showInfo("알림", "하나 이상의 메뉴 권한을 선택해주세요.");
      return;
    }
    setIsSaving(true);
    try {
      await apiSavePermissions(selectedUser.id, permissions);
      showInfo("알림", "저장되었습니다.");
    } catch {
      showInfo("알림", "저장에 실패했습니다.");
    } finally {
      setIsSaving(false);
    }
  }, [selectedUser, permissions, showInfo]);

  const handleBackup = useCallback(async () => {
    setIsBackingUp(true);
    try {
      await downloadDbBackup();
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      const msg =
        err instanceof Error ? err.message : "DB 백업에 실패했습니다.";
      showInfo("알림", msg);
    } finally {
      setIsBackingUp(false);
    }
  }, [showInfo]);

  return (
    <section className="settings-section">
      <div className="menu-perm__header">
        <h2 className="menu-perm__title">메뉴 권한</h2>
        <button
          className="menu-perm__action-btn menu-perm__action-btn--backup"
          disabled={isBackingUp}
          onClick={handleBackup}
        >
          {isBackingUp ? "백업 중..." : "DB 백업 다운로드"}
        </button>
      </div>

      <div className="menu-perm__panels">
        <div className="menu-perm__panel">
          <PersonTree
            groups={groups}
            selectedUserId={selectedUser?.id ?? null}
            onSelectUser={handleSelectUser}
          />
        </div>
        <div className="menu-perm__panel">
          <MenuTree
            selectedUserName={selectedUser?.username ?? null}
            permissions={permissions}
            onPermissionsChange={setPermissions}
            onSave={handleSave}
            isSaving={isSaving}
            canSave={!!selectedUser}
          />
        </div>
      </div>
    </section>
  );
}
