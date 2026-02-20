export type LogType =
  | "Request"
  | "Response"
  | "Receive"
  | "Send"
  | "Event"
  | "Logic"
  | "Error";

export type LogTag =
  | "OpentcsAPI"
  | "WebEvent"
  | "AppEvent"
  | "LogicEvent"
  | "ProcessEvent"
  | "VehicleEvent"
  | "TransportOrderEvent"
  | "ModelEvent"
  | "ConnectionEvent";

export type LogItem = {
  id: string;
  time: string;
  message: string;
  user: string;
  level: string;
  tag: LogTag;
  type: LogType;
  data: string | null;
};

export type LogFilterState = {
  message: string;
  robotSn: string;
  logType: LogType | "";
  logTag: LogTag | "";
  date: string | null;
  startTime: string;
  endTime: string;
};

export type DatePickerProps = {
  value: string | null;
  onChange: (date: string | null) => void;
  popupAlign?: "left" | "right";
};

export type TimeRangePickerProps = {
  startTime: string;
  endTime: string;
  onChange: (start: string, end: string) => void;
};
