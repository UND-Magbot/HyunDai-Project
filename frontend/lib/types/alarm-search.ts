export type AlarmSearchStatus = "Warning" | "Resume";

export type AlarmSearchItem = {
  id: string;
  code: string;
  status: AlarmSearchStatus;
  robotSn: string;
  message: string;
  timestamp: string;
};

export type AlarmSearchFilterState = {
  message: string;
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
  onFilterChange: (filters: AlarmSearchFilterState) => void;
  onSearch: () => void;
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
