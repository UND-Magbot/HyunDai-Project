export type TaskType = "Jacking" | "Transport" | "Disinfect" | "Park" | "Charge";

export type TaskMode = "DRIVING" | "STRICT_DRIVING";

export type RouteItem = {
  id: string;
  pathName: string;
  robotLabel: string;
  description: string;
};

export type CreateTaskFormState = {
  taskType: TaskType | "";
  robot: string;
  maxSpeed: number;
  mode: TaskMode | "";
  detourR: number;
  cycles: number;
  selectedRoutes: string[];
};

export type CreateTaskPayload = {
  taskType: TaskType;
  robot: string;
  maxSpeed: number;
  mode: TaskMode;
  detourR: number;
  cycles: number;
  routes: string[];
};

export type CreateTaskModalProps = {
  open: boolean;
  onClose: () => void;
};

/* ── Task List Page ── */

export type TaskListState =
  | "FINISHED"
  | "WAITING"
  | "InPROGRESS"
  | "PAUSED"
  | "UNROUTABLE"
  | "FAILED";

export type TaskListItem = {
  id: string;
  waybillNumber: string;
  taskId: string;
  robotSn: string;
  state: TaskListState;
  taskType: TaskType;
  createTime: string;
  endTime: string | null;
  start: string | null;
  end: string | null;
  passing: string | null;
};

export type TaskListFilterState = {
  waybillNum: string;
  robotSn: string;
  taskType: TaskType | "";
  state: TaskListState | "";
  dateStart: string | null;
  dateEnd: string | null;
};

export type TaskListFilterProps = {
  filters: TaskListFilterState;
  robotSns: string[];
  onFilterChange: (filters: TaskListFilterState) => void;
  onSearch: () => void;
};

export type TaskListTableProps = {
  tasks: TaskListItem[];
  onInfoClick: (taskId: string) => void;
};

export type DateRangePickerProps = {
  startDate: string | null;
  endDate: string | null;
  onChange: (start: string | null, end: string | null) => void;
};
