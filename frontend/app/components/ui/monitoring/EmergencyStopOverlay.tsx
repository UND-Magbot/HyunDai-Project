"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./EmergencyStopOverlay.css";

type Props = {
  onReturnAll: () => void;
};

export function EmergencyStopOverlay({ onReturnAll }: Props) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return createPortal(
    <div className="estop-overlay">
      <div className="estop-overlay__bg" />

      <div className="estop-overlay__content">
        {/* 비상정지 아이콘 */}
        <div className="estop-overlay__icon">
          <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            {/* 외곽 팔각형 */}
            <polygon
              points="24,4 56,4 76,24 76,56 56,76 24,76 4,56 4,24"
              fill="#cc0000"
              stroke="#ff4444"
              strokeWidth="3"
              className="estop-overlay__octagon"
            />
            {/* STOP 텍스트 */}
            <text x="40" y="46" textAnchor="middle" fill="#fff" fontSize="18" fontWeight="900" fontFamily="Arial, sans-serif">
              STOP
            </text>
          </svg>
        </div>

        <div className="estop-overlay__title">
          <span className="estop-overlay__icon-text">⛔</span>
          비 상 정 지
          <span className="estop-overlay__icon-text">⛔</span>
        </div>

        <div className="estop-overlay__subtitle">
          모든 로봇이 정지되었습니다
        </div>

        <button
          type="button"
          className="estop-overlay__return-btn"
          onClick={onReturnAll}
        >
          전체 복귀
        </button>

        <div className="estop-overlay__hint">
          전체 복귀 버튼을 눌러 로봇을 이동시키세요
        </div>
      </div>
    </div>,
    document.body
  );
}
