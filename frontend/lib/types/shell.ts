export type AlarmSeverity = "info" | "warning" | "error";

export type AlarmListItemProps = {
  code: string;
  severity: AlarmSeverity;
  timestamp: string;
  message: string;
  onClick?: () => void;
};

export type AlarmDetailData = {
  id: string;
  code: string;
  severity: AlarmSeverity;
  message: string;
  robot?: string;
  occurredAt: string;
  clearedAt?: string;
};

export type AlarmDetailProps = {
  alarm: AlarmDetailData;
  onClose: () => void;
};

export type AlarmData = {
  id: string;
  code: string;
  severity: AlarmSeverity;
  timestamp: string;
  message: string;
  robot?: string;
  occurredAt: string;
  clearedAt?: string;
};

export type FilterType = "all" | AlarmSeverity;

export type TopBarProps = {
  dateTime: string;
  onToggleNav?: () => void;
  navExpanded?: boolean;
};

export type NavItem = {
  label: string;
  href: string;
  match?: string;
  icon: string;
};

export type SideNavProps = {
  items: NavItem[];
  collapsed?: boolean;
  onClose?: () => void;
  onItemSelect?: () => void;
};

export type UserDropdownProps = {
  userName?: string;
};
