export type DevicePower = "online" | "offline";

export type DeviceStatus = "idle" | "running" | "charging" | "error" | "warning" | "disable";

export type TaskState = "running" | "completed" | "error";

export type DeviceRowProps = {
  id: string;
  name: string;
  power: DevicePower;
  battery: string;
  status: DeviceStatus;
  isExpanded?: boolean;
  onToggleExpand?: (deviceId: string) => void;
  onInfo?: (deviceId: string) => void;
  onCharge?: (deviceId: string) => void;
};

export type MockDevice = DeviceRowProps & { id: string };

export type TaskRowProps = {
  robot: string;
  endpoint: string;
  state: TaskState;
  duration: string;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
  onInfo?: () => void;
};

export type MockTask = TaskRowProps & { taskNum: string };

export type DeviceTaskState =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type DeviceBaseInfo = {
  sn: string;
  robotName: string | null;
  model: string | null;
  deploymentTime: string | null;
  apkVersion: string | null;
  sdkVersion: string | null;
};

export type DeviceOperational = {
  busiName: string | null;
  online: boolean;
  runState: string | null;
  power: number | null;
  signal: number | null;
  enable: boolean;
};

export type DeviceTask = {
  taskId: string;
  state: DeviceTaskState;
  type: string;
  createTime: string;
  start: string; // POI name (출발지)
  end: string; // POI name (도착지)
  oper: string;
};

export type DeviceDetail = DeviceBaseInfo &
  DeviceOperational & {
    currentTask: DeviceTask[];
  };

export type OverlayItem = {
  label: string;
  checked: boolean;
};

export type OverlayCardProps = {
  items: OverlayItem[];
  onItemToggle: (label: string, checked: boolean) => void;
};

export type LayerButtonProps = {
  isActive: boolean;
  onToggle: () => void;
};

export type MapModeButtonProps = {
  mapMode: "2d" | "3d";
  onMapModeChange: (mode: "2d" | "3d") => void;
};

export type TaskInfoStatus = "completed" | "failed" | "running" | "pending";

export type TaskLogLevel = "info" | "warning" | "error";

export type TaskLogEntry = {
  message: string;
  timestamp: string;
  level: TaskLogLevel;
};

export type TaskDetail = {
  waybillNumber: string;
  business: string;
  taskType: string;
  priority: string;
  start: string;
  end: string;
  pass: string | null;
  startTime: string;
  endTime: string;
  status: TaskInfoStatus;
  routeMode: string;
  detourRadius: number;
  speed: number;
  logs: TaskLogEntry[];
};

export type TaskInfoModalProps = {
  taskId: string | null;
  onClose: () => void;
};
