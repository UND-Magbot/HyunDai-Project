export type ErrorCategory = "시스템" | "로봇" | "사용자";

export type LogItem = {
  id: string;
  time: string;
  errorType: ErrorCategory;
  ip: string;
  message: string;
  data: string | null;
};

export type LogFilterState = {
  message: string;
  errorType: ErrorCategory | "";
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
