"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./ReturningOverlay.css";

type Props = {
  /** "returning" = 복귀 중, "entering" = 작업위치 이동 중 */
  mode: "returning" | "entering";
  /** 카운트다운 잔여 초 (null이면 미표시) */
  countdown?: number | null;
  /** 카운트다운 0 도달 시 호출 */
  onCountdownEnd?: () => void;
};

const CONFIG = {
  returning: {
    title: "모든 로봇 복귀 중",
    subtitle: "로봇들이 충전소/대기지점으로 돌아가고 있습니다",
    hint: "모든 로봇이 복귀하면 자동으로 닫힙니다",
  },
  entering: {
    title: "작업 위치로 이동 중",
    subtitle: "로봇들이 저장된 작업 위치로 이동하고 있습니다",
    hint: "모든 로봇이 도착하면 자동으로 작업을 시작합니다",
  },
};

export function ReturningOverlay({ mode, countdown, onCountdownEnd }: Props) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const [localCountdown, setLocalCountdown] = useState<number | null>(null);
  const cfg = CONFIG[mode];

  useEffect(() => {
    setMounted(true);
    const raf = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    if (countdown != null && countdown > 0) {
      setLocalCountdown(countdown);
    }
  }, [countdown]);

  useEffect(() => {
    if (localCountdown == null || localCountdown <= 0) {
      if (localCountdown === 0 && onCountdownEnd) onCountdownEnd();
      return;
    }
    const timer = setInterval(() => {
      setLocalCountdown((prev) => {
        if (prev == null || prev <= 1) return 0;
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [localCountdown != null && localCountdown > 0]);

  if (!mounted) return null;

  return createPortal(
    <div className={`returning-banner${visible ? " returning-banner--visible" : ""}`}>
      <div className="returning-banner__bar">
        {/* 아이콘 */}
        <div className="returning-banner__icon">
          <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="40" cy="40" r="34" fill="#1565c0" stroke="#42a5f5" strokeWidth="3"
              className="returning-banner__circle" />
            {mode === "returning" ? (
              <path d="M50 35 L40 25 L30 35 M40 25 L40 55" stroke="#fff" strokeWidth="4"
                strokeLinecap="round" strokeLinejoin="round" fill="none"
                className="returning-banner__arrow" />
            ) : (
              <path d="M30 45 L40 55 L50 45 M40 55 L40 25" stroke="#fff" strokeWidth="4"
                strokeLinecap="round" strokeLinejoin="round" fill="none"
                className="returning-banner__arrow" />
            )}
          </svg>
        </div>

        <div className="returning-banner__title">{cfg.title}</div>
        <div className="returning-banner__subtitle">{cfg.subtitle}</div>

        {/* 카운트다운 or 로딩 점 */}
        {localCountdown != null && localCountdown > 0 ? (
          <div className="returning-banner__countdown">
            <span className="returning-banner__countdown-num">{localCountdown}</span>
            <span className="returning-banner__countdown-label">초 후 작업 시작</span>
          </div>
        ) : (
          <div className="returning-banner__dots">
            <span className="returning-banner__dot" />
            <span className="returning-banner__dot" />
            <span className="returning-banner__dot" />
          </div>
        )}

        <div className="returning-banner__hint">{cfg.hint}</div>
      </div>
    </div>,
    document.body
  );
}
