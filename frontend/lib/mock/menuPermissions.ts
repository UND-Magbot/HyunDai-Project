import type { MenuPermissionItem } from "@/lib/types/settings";
import { MENU_ITEMS } from "@/lib/types/settings";

export const defaultMenuPermissions: MenuPermissionItem[] = MENU_ITEMS.map(
  (item) => ({
    menuKey: item.key,
    menuLabel: item.label,
    isAllowed: true,
  })
);
