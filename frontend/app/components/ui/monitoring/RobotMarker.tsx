import type { CSSProperties } from "react";
import type { RobotMarkerData } from "@/lib/types/map-markers";

type Props = {
  data: RobotMarkerData;
  leftPercent: number;
  topPercent: number;
};

function radToDeg(rad: number): number {
  return -(rad * 180) / Math.PI + 90;
}

export function RobotMarker({ data, leftPercent, topPercent }: Props) {
  const style: CSSProperties = {
    "--marker-left": `${leftPercent}%`,
    "--marker-top": `${topPercent}%`,
    "--robot-yaw": `${radToDeg(data.yaw)}deg`,
  } as CSSProperties;

  const statusModifier =
    data.status === "error" || data.status === "warning"
      ? `map-marker--robot-${data.status}`
      : "";
  const collisionModifier =
    data.collisionState && data.collisionState !== "none"
      ? `map-marker--robot-${data.collisionState}`
      : "";

  return (
    <div
      className={`map-marker map-marker--robot ${statusModifier} ${collisionModifier}`.trim()}
      style={style}
    >
      <div className="map-marker__body" aria-hidden="true">
        <div className="map-marker__robot-triangle" />
        <div className="map-marker__robot-ring" />
      </div>
      <span className="map-marker__label">{data.robotName}</span>
    </div>
  );
}
