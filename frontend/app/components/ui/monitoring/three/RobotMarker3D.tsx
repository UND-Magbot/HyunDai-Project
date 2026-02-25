"use client";

import { memo } from "react";
import { Billboard, Text } from "@react-three/drei";
import type { RobotMarkerData } from "@/lib/types/map-markers";
import { mapPixelToWorld } from "./mapCoords";

type Props = {
  robot: RobotMarkerData;
  imgW: number;
  imgH: number;
};

const BODY_W = 12;
const BODY_H = 14;
const BODY_D = 10;

function getLedColor(
  status: RobotMarkerData["status"],
  collisionState?: RobotMarkerData["collisionState"]
): string {
  if (collisionState === "collision") return "#ff5757";
  if (collisionState === "near_miss") return "#ffba24";
  if (status === "error") return "#ff5757";
  if (status === "warning") return "#ffba24";
  return "#42d8ff";
}

function RobotMarker3DInner({ robot, imgW, imgH }: Props) {
  const [x, , z] = mapPixelToWorld(robot.position, imgW, imgH);
  const { yaw, robotName, status, collisionState } = robot;

  const ledColor = getLedColor(status, collisionState);
  const rotationY = -yaw + Math.PI / 2;

  return (
    <group position={[x, 0, z]}>
      <group rotation={[0, rotationY, 0]}>
        {/* 바디 (둥근 직사각형) */}
        <mesh position={[0, BODY_H / 2, 0]}>
          <boxGeometry args={[BODY_W, BODY_H, BODY_D]} />
          <meshStandardMaterial color="#d8dce4" />
        </mesh>

        {/* LED 스트립 (우측 전면) */}
        <mesh position={[BODY_W / 2 + 0.3, BODY_H / 2, -BODY_D * 0.2]}>
          <boxGeometry args={[0.6, BODY_H * 0.65, 1]} />
          <meshStandardMaterial
            color={ledColor}
            emissive={ledColor}
            emissiveIntensity={0.8}
            toneMapped={false}
          />
        </mesh>

        {/* 방향 표시 (전면 삼각형) */}
        <mesh position={[0, BODY_H + 2, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <coneGeometry args={[4, 6, 3]} />
          <meshStandardMaterial
            color={ledColor}
            emissive={ledColor}
            emissiveIntensity={0.4}
            toneMapped={false}
          />
        </mesh>
      </group>

      {/* Label */}
      <Billboard position={[0, BODY_H + 10, 0]}>
        <Text fontSize={8} color="#42d8ff" anchorY="bottom">
          {robotName}
        </Text>
      </Billboard>
    </group>
  );
}

export const RobotMarker3D = memo(RobotMarker3DInner);
