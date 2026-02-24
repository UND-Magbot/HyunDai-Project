export type AlarmSearchStatus = "Warning" | "Resume";

import type { AlarmErrorType } from "@/lib/types/shell";

export type AlarmSearchItem = {
  id: string;
  code: string;
  errorType: AlarmErrorType;
  status: AlarmSearchStatus;
  robotSn: string;
  message: string;
  timestamp: string;
};

export type AlarmSearchFilterState = {
  message: string;
  errorType: string;
  code: string;
  robotSn: string;
  date: string | null;
  startTime: string;
  endTime: string;
};

export type AlarmSearchParams = AlarmSearchFilterState & {
  page: number;
  pageSize: number;
};

export type AlarmSearchResponse = {
  items: AlarmSearchItem[];
  total: number;
  page: number;
  pageSize: number;
};

export type AlarmSearchFilterProps = {
  filters: AlarmSearchFilterState;
  robotSns: string[];
  errorTypes: { value: string; label: string }[];
  codes: string[];
  onFilterChange: (filters: AlarmSearchFilterState) => void;
  onSearch: () => void;
  onReset: () => void;
};

export type AlarmSearchItemProps = {
  item: AlarmSearchItem;
};

export type AlarmSearchPaginationProps = {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
};
