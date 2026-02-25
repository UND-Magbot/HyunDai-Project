"use client";

import { memo } from "react";
import { Billboard, Text } from "@react-three/drei";
import type { PoiMarkerData } from "@/lib/types/map-markers";
import { mapPixelToWorld } from "./mapCoords";

type Props = {
  poi: PoiMarkerData;
  imgW: number;
  imgH: number;
};

function PoiMarker3DInner({ poi, imgW, imgH }: Props) {
  const [x, , z] = mapPixelToWorld(poi.position, imgW, imgH);
  const isCharging = poi.type === "charging";
  const renderKind = poi.renderKind ?? (isCharging ? "circle" : "triangle");

  return (
    <group position={[x, 0, z]}>
      {renderKind === "circle" ? (
        <>
          {/* Dark cylinder base */}
          <mesh position={[0, 5, 0]}>
            <cylinderGeometry args={[6, 6, 10, 16]} />
            <meshStandardMaterial
              color="#232d37"
              transparent
              opacity={0.86}
            />
          </mesh>
          {/* Red inner dot */}
          <mesh position={[0, 10.5, 0]}>
            <sphereGeometry args={[2.5, 8, 8]} />
            <meshStandardMaterial
              color="#ff2b2b"
              emissive="#ff4a4a"
              emissiveIntensity={0.65}
            />
          </mesh>
        </>
      ) : (
        /* Blue cone for non-charging */
        <mesh position={[0, 7, 0]}>
          <coneGeometry args={[6, 14, 3]} />
          <meshStandardMaterial
            color="#1f6fff"
            emissive="#1f6fff"
            emissiveIntensity={0.35}
          />
        </mesh>
      )}

      {/* Angle direction indicator */}
      {poi.angle != null && <AngleIndicator angle={poi.angle} />}

      {/* Label */}
      <Billboard position={[0, 18, 0]}>
        <Text fontSize={7} color="#ffffff" anchorY="bottom">
          {poi.label}
        </Text>
      </Billboard>
    </group>
  );
}

function AngleIndicator({ angle }: { angle: number }) {
  const angleRad = (angle * Math.PI) / 180;
  const len = 18;
  const endX = Math.cos(angleRad) * len;
  const endZ = -Math.sin(angleRad) * len;

  return (
    <group position={[0, 5, 0]}>
      {/* Direction line using a thin cylinder */}
      <mesh
        position={[endX / 2, 0, endZ / 2]}
        rotation={[0, -angleRad, 0]}
      >
        <cylinderGeometry args={[0.8, 0.8, len, 4]} />
        <meshBasicMaterial color="#ffc83c" transparent opacity={0.9} />
      </mesh>
      {/* Arrowhead */}
      <mesh
        position={[endX, 0, endZ]}
        rotation={[0, -angleRad, -Math.PI / 2]}
      >
        <coneGeometry args={[2.5, 6, 4]} />
        <meshBasicMaterial color="#ffc83c" transparent opacity={0.9} />
      </mesh>
    </group>
  );
}

export const PoiMarker3D = memo(PoiMarker3DInner);
