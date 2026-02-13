"use client";

import { IconButton } from "../IconButton";
import type { TaskRowProps } from "@/lib/types/monitoring";

export function TaskRow({
  robot,
  endpoint,
  state,
  duration,
  isExpanded = false,
  onToggleExpand,
  onInfo,
}: TaskRowProps) {
  const expanded = isExpanded;
  const canState = state === "running";
  const canCancel = state === "running";
  const canInfo =
    state === "running" || state === "completed" || state === "error";

  return (
    <div className={`task-row${expanded ? " task-row--expanded" : ""}`} onClick={onToggleExpand}>
      <button
        type="button"
        className="task-row__summary"
        aria-expanded={expanded}
      >
        <span className="task-row__cell task-row__cell--robot">{robot}</span>
        <span className="task-row__cell task-row__cell--endpoint">
          {endpoint}
        </span>
        <span className="task-row__cell task-row__cell--state">{state}</span>
        <span className="task-row__cell task-row__cell--duration">
          {duration}
        </span>
      </button>
      {expanded ? (
        <div
          className="task-row__actions"
          onClick={(event) => event.stopPropagation()}
        >
          <IconButton aria-label="State" disabled={!canState}>
            State
          </IconButton>
          <IconButton aria-label="Cancel" disabled={!canCancel}>
            Cancel
          </IconButton>
          <IconButton
            aria-label="Info"
            disabled={!canInfo}
            onClick={canInfo ? onInfo : undefined}
          >
            Info
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}
