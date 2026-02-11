import type { AlarmSeverity, AlarmListItemProps } from "@/lib/types/shell";

const severityLabels: Record<AlarmSeverity, string> = {
  info: "Info",
  warning: "Warning",
  error: "Error",
};

export function AlarmListItem({
  code,
  severity,
  timestamp,
  message,
  onClick,
}: AlarmListItemProps) {
  return (
    <button className="alarm-item" onClick={onClick} type="button">
      <div className="alarm-item__header">
        <span
          className={`alarm-item__code-severity alarm-item__severity--${severity}`}
        >
          [{code}] {severityLabels[severity]}
        </span>
        <span className="alarm-item__timestamp">{timestamp}</span>
      </div>
      <p className="alarm-item__message">{message}</p>
    </button>
  );
}
