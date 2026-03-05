"use client";

import { memo } from "react";
import { Billboard, Text, RoundedBox } from "@react-three/drei";
import type { RobotMarkerData } from "@/lib/types/map-markers";
import { mapPixelToWorld } from "./mapCoords";

type Props = {
  robot: RobotMarkerData;
  imgW: number;
  imgH: number;
};

/* ── 캐스터 바퀴 ──────────────────────────── */
const CASTER_R = 0.9;
const CASTER_W = 0.6;

/* ── 베이스 ─────────────────────────────── */
const BASE_BOT = CASTER_R * 2 + 0.15; // 캐스터 상단 + 약간의 간격
const BASE_W = 9;
const BASE_H = 3;
const BASE_D = 12;

/* ── 기둥 (전방/후방, 직사면체) ──────────── */
const PILLAR_W = 3;
const PILLAR_H = 22;
const PILLAR_D = 1.2;
const PILLAR_BOT = BASE_BOT + BASE_H;
const PILLAR_Z_FRONT = 3.5;
const PILLAR_Z_REAR = -3.5;

/* ── 선반 (두 기둥 사이) ─────────────────── */
const SHELF_W = 9;
const SHELF_H = 0.5;
const SHELF_D = 7;
const SHELF_Ys = [16];

/* ── 스크린 (전방 기둥 상단) ──────────────── */
const SCREEN_W = 7;
const SCREEN_H = 4.5;
const SCREEN_D = 1.0;
const SCREEN_TILT = -0.2;

/* ── LED (후방 기둥 양쪽) ─────────────────── */
const LED_STRIP_W = 0.3;
const LED_STRIP_H = 18;
const LED_STRIP_D = 0.3;

const LABEL_Y = PILLAR_BOT + PILLAR_H + 8;

/* ── LED 색상 ──────────────────────────────── */
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

/* ── 컴포넌트 ──────────────────────────────── */
function RobotMarker3DInner({ robot, imgW, imgH }: Props) {
  const [x, , z] = mapPixelToWorld(robot.position, imgW, imgH);
  const { yaw, robotName, status, collisionState } = robot;

  const ledColor = getLedColor(status, collisionState);
  const rotationY = -yaw + Math.PI / 2;
  const pillarCY = PILLAR_BOT + PILLAR_H / 2;

  return (
    <group position={[x, 0, z]}>
      {/* ── 본체 (yaw 회전) ── */}
      <group rotation={[0, rotationY, 0]}>

        {/* ========== 베이스 ========== */}
        {/* 메인 바디 */}
        <RoundedBox args={[BASE_W, BASE_H, BASE_D]} radius={0.5} smoothness={4} position={[0, BASE_BOT + BASE_H / 2, 0]}>
          <meshStandardMaterial color="#ffffff" />
        </RoundedBox>
        {/* 상단 다크 밴드 */}
        <RoundedBox args={[BASE_W + 0.2, 0.4, BASE_D + 0.2]} radius={0.1} smoothness={2} position={[0, BASE_BOT + BASE_H + 0.1, 0]}>
          <meshStandardMaterial color="#555" metalness={0.4} roughness={0.5} />
        </RoundedBox>
        {/* 하단 다크 밴드 */}
        <RoundedBox args={[BASE_W + 0.1, 0.3, BASE_D + 0.1]} radius={0.1} smoothness={2} position={[0, BASE_BOT + 0.15, 0]}>
          <meshStandardMaterial color="#555" />
        </RoundedBox>
        {/* 전면 패널 */}
        <RoundedBox args={[5, 1.5, 0.3]} radius={0.15} smoothness={2} position={[0, BASE_BOT + BASE_H / 2, BASE_D / 2 + 0.15]}>
          <meshStandardMaterial color="#eeeeee" />
        </RoundedBox>
        {/* 전면 센서 (좌/우) */}
        <mesh position={[-1.5, BASE_BOT + BASE_H / 2, BASE_D / 2 + 0.1]}>
          <sphereGeometry args={[0.3, 6, 6]} />
          <meshStandardMaterial color="#777" />
        </mesh>
        <mesh position={[1.5, BASE_BOT + BASE_H / 2, BASE_D / 2 + 0.1]}>
          <sphereGeometry args={[0.3, 6, 6]} />
          <meshStandardMaterial color="#777" />
        </mesh>

        {/* 캐스터 바퀴 ×4 (전방 2 + 후방 2, 세로 배치) */}
        {(
          [
            [-2.5, BASE_D / 2 - 1],
            [2.5, BASE_D / 2 - 1],
            [-2.5, -(BASE_D / 2 - 1)],
            [2.5, -(BASE_D / 2 - 1)],
          ] as const
        ).map(([cx, cz], i) => (
          <group key={`cw${i}`} position={[cx, CASTER_R, cz]} rotation={[0, 0, Math.PI / 2]}>
            {/* 타이어 */}
            <mesh>
              <cylinderGeometry args={[CASTER_R, CASTER_R, CASTER_W, 16]} />
              <meshStandardMaterial color="#2a2a2a" />
            </mesh>
            {/* 허브 */}
            <mesh position={[0, CASTER_W / 2 + 0.01, 0]}>
              <cylinderGeometry args={[CASTER_R * 0.5, CASTER_R * 0.5, 0.08, 12]} />
              <meshStandardMaterial color="#c0c0c0" metalness={0.6} roughness={0.3} />
            </mesh>
            <mesh position={[0, -(CASTER_W / 2 + 0.01), 0]}>
              <cylinderGeometry args={[CASTER_R * 0.5, CASTER_R * 0.5, 0.08, 12]} />
              <meshStandardMaterial color="#c0c0c0" metalness={0.6} roughness={0.3} />
            </mesh>
          </group>
        ))}

        {/* ========== 전방 기둥 (직사면체) ========== */}
        <RoundedBox args={[PILLAR_W, PILLAR_H, PILLAR_D]} radius={0.4} smoothness={4} position={[0, pillarCY, PILLAR_Z_FRONT]}>
          <meshStandardMaterial color="#ffffff" />
        </RoundedBox>

        {/* ========== 후방 기둥 (직사면체) ========== */}
        <RoundedBox args={[PILLAR_W, PILLAR_H, PILLAR_D]} radius={0.4} smoothness={4} position={[0, pillarCY, PILLAR_Z_REAR]}>
          <meshStandardMaterial color="#ffffff" />
        </RoundedBox>

        {/* ========== 선반 (두 기둥 사이) ========== */}
        {SHELF_Ys.map((sy, i) => (
          <group key={`s${i}`}>
            {/* 선반 트레이 */}
            <RoundedBox args={[SHELF_W, SHELF_H, SHELF_D]} radius={0.15} smoothness={2} position={[0, sy, 0]}>
              <meshStandardMaterial color="#f5f5f5" />
            </RoundedBox>
            {/* 선반 전면 엣지 */}
            <RoundedBox args={[SHELF_W, SHELF_H, 0.1]} radius={0.05} smoothness={2} position={[0, sy, SHELF_D / 2 + 0.05]}>
              <meshStandardMaterial color="#eeeeee" />
            </RoundedBox>
          </group>
        ))}

        {/* ========== 후방 기둥 양쪽 LED ========== */}
        {/* LED 좌 */}
        <RoundedBox
          args={[LED_STRIP_W, LED_STRIP_H, LED_STRIP_D]}
          radius={0.1}
          smoothness={2}
          position={[
            -(PILLAR_W / 2 + 0.5),
            PILLAR_BOT + LED_STRIP_H / 2 + 1,
            PILLAR_Z_REAR,
          ]}
        >
          <meshStandardMaterial
            color={ledColor}
            emissive={ledColor}
            emissiveIntensity={0.9}
            toneMapped={false}
          />
        </RoundedBox>
        {/* LED 우 */}
        <RoundedBox
          args={[LED_STRIP_W, LED_STRIP_H, LED_STRIP_D]}
          radius={0.1}
          smoothness={2}
          position={[
            PILLAR_W / 2 + 0.5,
            PILLAR_BOT + LED_STRIP_H / 2 + 1,
            PILLAR_Z_REAR,
          ]}
        >
          <meshStandardMaterial
            color={ledColor}
            emissive={ledColor}
            emissiveIntensity={0.9}
            toneMapped={false}
          />
        </RoundedBox>

        {/* ========== 카메라 (전방 기둥 상단 정면) ========== */}
        <RoundedBox
          args={[1.8, 1.2, 0.8]}
          radius={0.2}
          smoothness={2}
          position={[
            0,
            PILLAR_BOT + PILLAR_H - 2,
            PILLAR_Z_FRONT + PILLAR_D / 2 + 0.4,
          ]}
        >
          <meshStandardMaterial color="#333" />
        </RoundedBox>

        {/* ========== 스크린 (전방 기둥 상단) ========== */}
        {/* 브래킷 */}
        <RoundedBox
          args={[1.8, 1.2, 1.5]}
          radius={0.2}
          smoothness={2}
          position={[0, PILLAR_BOT + PILLAR_H + 0.3, PILLAR_Z_FRONT + 0.8]}
        >
          <meshStandardMaterial color="#444" />
        </RoundedBox>
        {/* 스크린 (프레임 + 화면) */}
        <group
          position={[0, PILLAR_BOT + PILLAR_H + 2.5, PILLAR_Z_FRONT + 1]}
          rotation={[SCREEN_TILT, 0, 0]}
        >
          {/* 프레임 */}
          <RoundedBox args={[SCREEN_W, SCREEN_H, SCREEN_D]} radius={0.4} smoothness={4}>
            <meshStandardMaterial color="#2a2a2a" />
          </RoundedBox>
          {/* 화면 */}
          <mesh position={[0, 0, SCREEN_D / 2 + 0.01]}>
            <boxGeometry args={[SCREEN_W - 0.8, SCREEN_H - 0.8, 0.05]} />
            <meshStandardMaterial
              color="#b8c4d0"
              emissive="#90a0b0"
              emissiveIntensity={0.3}
            />
          </mesh>
        </group>

        {/* 상단 센서 (빨간 점) */}
        <mesh
          position={[0, PILLAR_BOT + PILLAR_H + 5.2, PILLAR_Z_FRONT + 1]}
        >
          <sphereGeometry args={[0.5, 8, 8]} />
          <meshStandardMaterial
            color="#ff3333"
            emissive="#ff3333"
            emissiveIntensity={0.5}
          />
        </mesh>
      </group>

      {/* ── 라벨 ── */}
      <Billboard position={[0, LABEL_Y, 0]}>
        <Text fontSize={8} color={ledColor} anchorY="bottom">
          {robotName}
        </Text>
      </Billboard>
    </group>
  );
}

export const RobotMarker3D = memo(RobotMarker3DInner);
