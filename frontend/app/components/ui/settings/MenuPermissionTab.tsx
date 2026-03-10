"use client";

import { useState, useCallback, useEffect } from "react";
import { useAlert } from "@/lib/context/AlertContext";
import { PersonTree } from "./PersonTree";
import { MenuTree } from "./MenuTree";
import {
  fetchUsers,
  getMenuPermissions,
  saveMenuPermissions as apiSavePermissions,
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

  return (
    <section className="settings-section">
      <div className="menu-perm__header">
        <h2 className="menu-perm__title">메뉴 권한</h2>
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
