import type {
  AlarmSearchItem,
  AlarmSearchParams,
  AlarmSearchResponse,
} from "@/lib/types/alarm-search";
import { getErrorTypeFromCode } from "@/lib/constants/alarm";

const ROBOT_SNS = [
  "AMR-001",
  "AMR-002",
  "AMR-003",
  "AMR-004",
  "AMR-005",
  "AMR-006",
  "AMR-007",
  "AMR-008",
  "AMR-009",
  "AMR-010",
];

const CODES = [
  "ALM-1001",
  "ALM-1002",
  "ALM-1003",
  "ALM-2001",
  "ALM-2002",
  "ALM-2003",
  "ALM-3001",
  "ALM-3002",
  "ALM-3003",
  "ALM-4001",
];

const MESSAGES = [
  "Communication timeout detected",
  "Battery level critically low",
  "Motor driver overheating",
  "Obstacle sensor malfunction",
  "Navigation path blocked",
  "Emergency stop triggered",
  "Wheel encoder error",
  "Charging station connection lost",
  "Task execution timeout",
  "LIDAR scan abnormal",
  "Network connection unstable",
  "Firmware version mismatch",
  "Payload weight exceeded",
  "Safety zone breach detected",
  "IMU calibration error",
];

function generateMockAlarms(): AlarmSearchItem[] {
  const items: AlarmSearchItem[] = [];
  const now = new Date();
  const baseDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 8, 0, 0);

  for (let i = 0; i < 53; i++) {
    const offsetMinutes = i * 17 + Math.floor(i * 3.7);
    const ts = new Date(baseDate.getTime() + offsetMinutes * 60000);

    const yyyy = ts.getFullYear();
    const mm = String(ts.getMonth() + 1).padStart(2, "0");
    const dd = String(ts.getDate()).padStart(2, "0");
    const hh = String(ts.getHours()).padStart(2, "0");
    const min = String(ts.getMinutes()).padStart(2, "0");
    const sec = String(ts.getSeconds()).padStart(2, "0");

    const code = CODES[i % CODES.length];

    items.push({
      id: String(i + 1),
      code,
      errorType: getErrorTypeFromCode(code),
      status: i % 3 === 0 ? "Resume" : "Warning",
      robotSn: ROBOT_SNS[i % ROBOT_SNS.length],
      message: MESSAGES[i % MESSAGES.length],
      timestamp: `${yyyy}-${mm}-${dd} ${hh}:${min}:${sec}`,
    });
  }

  return items.reverse();
}

const mockAlarmSearchData = generateMockAlarms();

export function getDistinctAlarmRobotSNs(): string[] {
  return [...new Set(mockAlarmSearchData.map((a) => a.robotSn))].sort();
}

export function getDistinctAlarmCodes(): string[] {
  return [...new Set(mockAlarmSearchData.map((a) => a.code))].sort();
}

export function getTodayAlarms(): AlarmSearchItem[] {
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, "0");
  const dd = String(today.getDate()).padStart(2, "0");
  const todayPrefix = `${yyyy}-${mm}-${dd}`;
  return mockAlarmSearchData.filter((a) => a.timestamp.startsWith(todayPrefix));
}

export function searchAlarms(params: AlarmSearchParams): AlarmSearchResponse {
  let filtered = mockAlarmSearchData;

  if (params.message) {
    const keyword = params.message.toLowerCase();
    filtered = filtered.filter((a) =>
      a.message.toLowerCase().includes(keyword)
    );
  }

  if (params.errorType) {
    filtered = filtered.filter((a) => a.errorType === params.errorType);
  }

  if (params.code) {
    filtered = filtered.filter((a) => a.code === params.code);
  }

  if (params.robotSn) {
    filtered = filtered.filter((a) => a.robotSn === params.robotSn);
  }

  if (params.date) {
    filtered = filtered.filter((a) => a.timestamp.startsWith(params.date!));
  }

  const isDefaultTime =
    params.startTime === "00:00" && params.endTime === "23:59";
  if (params.startTime && params.endTime && !isDefaultTime) {
    filtered = filtered.filter((a) => {
      const time = a.timestamp.split(" ")[1]?.substring(0, 5) ?? "";
      return time >= params.startTime && time <= params.endTime;
    });
  }

  const total = filtered.length;
  const start = (params.page - 1) * params.pageSize;
  const items = filtered.slice(start, start + params.pageSize);

  return {
    items,
    total,
    page: params.page,
    pageSize: params.pageSize,
  };
}
