import type { AlarmErrorType } from "@/lib/types/shell";

/** 알람 코드 접두사 → 오류 타입 매핑 */
const ALARM_CODE_ERROR_TYPE_MAP: Record<string, AlarmErrorType> = {
  "ALM-1": "network",
  "ALM-2": "battery",
  "ALM-3": "task",
  "ALM-4": "task",
};

/** 오류 타입 → 한국어 라벨 */
export const ALARM_ERROR_TYPE_LABELS: Record<AlarmErrorType, string> = {
  network: "통신 오류",
  battery: "배터리 오류",
  task: "작업 오류",
};

/** 알람 코드에서 오류 타입을 추출 */
export function getErrorTypeFromCode(code: string): AlarmErrorType {
  const prefix = code.substring(0, 5);
  return ALARM_CODE_ERROR_TYPE_MAP[prefix] ?? "task";
}
