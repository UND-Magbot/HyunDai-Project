export interface BusinessGroup {
  id: string;
  name: string;
  users: BusinessUser[];
}

export interface BusinessUser {
  id: number;
  loginId: string;
  username: string;
  role: number;
  roleName: string;
}

export interface MenuPermissionItem {
  menuKey: string;
  menuLabel: string;
  isAllowed: boolean;
  menuId?: number;
  parentId?: number | null;
}

export const MENU_ITEMS = [
  { key: "monitoring", label: "모니터링" },
  { key: "robots", label: "로봇관리" },
  { key: "logs", label: "로그관리" },
  { key: "map", label: "맵관리" },
  { key: "settings", label: "설정" },
] as const;
