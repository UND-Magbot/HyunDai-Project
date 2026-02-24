"use client";

import { useState, useEffect, useCallback } from "react";
import { Modal } from "./Modal";
import type { RobotDeviceInfoProps } from "@/lib/types/robots";
import "./RobotDeviceInfo.css";

function formatValue(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  return String(value);
}

export function RobotDeviceInfo({
  device,
  onClose,
  onEnableToggle,
  togglingDeviceId,
}: RobotDeviceInfoProps) {
  const [initialMinBattery, setInitialMinBattery] = useState<number | null>(null);
  const [minBattery, setMinBattery] = useState(20);
  const [isApplying, setIsApplying] = useState(false);

  useEffect(() => {
    if (!device) return;
    const controller = new AbortController();

    fetch(
      `${process.env.NEXT_PUBLIC_API_URL}/api/robots/sn/${encodeURIComponent(device.sn)}/min-battery`,
      { signal: controller.signal }
    )
      .then((res) => res.json())
      .then((data: { min_battery: number }) => {
        setInitialMinBattery(data.min_battery);
        setMinBattery(data.min_battery);
      })
      .catch(() => {
        setInitialMinBattery(20);
        setMinBattery(20);
      });

    return () => controller.abort();
  }, [device]);

  const handleApplyMinBattery = useCallback(async () => {
    if (!device || isApplying) return;
    setIsApplying(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/robots/sn/${encodeURIComponent(device.sn)}/min-battery`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ min_battery: minBattery }),
        }
      );
      if (res.ok) {
        const data: { min_battery: number } = await res.json();
        setInitialMinBattery(data.min_battery);
      }
    } finally {
      setIsApplying(false);
    }
  }, [device, minBattery, isApplying]);

  if (!device) return null;

  const isToggleDisabled = togglingDeviceId === device.id;
  const isMinBatteryChanged = initialMinBattery !== null && minBattery !== initialMinBattery;

  const shouldScrollTaskTable = device.currentTask.length > 5;

  const renderPower = () => {
    if (device.power == null) return "-";

    return (
      <span className={`robot-info__power-value${device.power <= 30 ? " robot-info__power-value--danger" : ""}`}>
        {device.power}%
      </span>
    );
  };

  return (
    <Modal open onClose={onClose} title="로봇 상세 정보" width="760px">
      <div className="robot-info">
        {/* Base Information */}
        <section className="robot-info__section">
          <h3 className="robot-info__section-title">기본 정보</h3>
          <div className="robot-info__grid">
            <div className="robot-info__field">
              <span className="robot-info__label">로봇 SN</span>
              <span className="robot-info__value">
                {formatValue(device.sn)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">로봇 명</span>
              <span className="robot-info__value">
                {formatValue(device.robotName)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">모델</span>
              <span className="robot-info__value">
                {formatValue(device.model)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">배포일</span>
              <span className="robot-info__value">
                {formatValue(device.deploymentTime)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">APK 버전</span>
              <span className="robot-info__value">
                {formatValue(device.apkVersion)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">SDK 버전</span>
              <span className="robot-info__value">
                {formatValue(device.sdkVersion)}
              </span>
            </div>
          </div>
        </section>

        {/* Operational */}
        <section className="robot-info__section">
          <h3 className="robot-info__section-title">운영 정보</h3>
          <div className="robot-info__grid">
            <div className="robot-info__field">
              <span className="robot-info__label">고객사</span>
              <span className="robot-info__value">
                {formatValue(device.busiName)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">전원</span>
              <span
                className={`robot-info__value robot-info__value--${device.online ? "online" : "offline"}`}
              >
                {device.online ? "Online" : "Offline"}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">운행 상태</span>
              <span className="robot-info__value">
                {formatValue(device.runState)}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">배터리</span>
              <span className="robot-info__value">{renderPower()}</span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">Signal</span>
              <span className="robot-info__value">
                {device.signal != null ? `${device.signal}` : "-"}
              </span>
            </div>
            <div className="robot-info__field">
              <span className="robot-info__label">활성 상태</span>
              <label className="robot-info__toggle">
                <input
                  type="checkbox"
                  checked={device.enable}
                  onChange={() => onEnableToggle(device.id)}
                  disabled={isToggleDisabled}
                />
                <span className="robot-info__toggle-slider" />
              </label>
            </div>
          </div>

          <div className="robot-info__battery-row">
            <span className="robot-info__label">최소 배터리</span>
            <input
              type="range"
              className="robot-info__range"
              min={0}
              max={100}
              value={minBattery}
              onChange={(e) => setMinBattery(Number(e.target.value))}
              style={{
                background: `linear-gradient(to right, var(--color-primary) ${minBattery}%, var(--bg-surface-2) ${minBattery}%)`,
              }}
            />
            <span className="robot-info__range-value">{minBattery}%</span>
            <button
              type="button"
              className="robot-info__apply-btn"
              disabled={!isMinBatteryChanged || isApplying}
              onClick={handleApplyMinBattery}
            >
              {isApplying ? "적용 중..." : "적용"}
            </button>
          </div>
        </section>

        {/* Current Task */}
        {/* <section className="robot-info__section">
          <h3 className="robot-info__section-title">진행 작업</h3>
          {device.currentTask.length === 0 ? (
            <div className="robot-info__empty">진행중인 작업이 없습니다.</div>
          ) : (
            <div
              className={`robot-info__table-wrapper${shouldScrollTaskTable ? " robot-info__table-wrapper--scroll" : ""}`}
            >
              <table className="robot-info__table">
                <thead>
                  <tr>
                    <th>작업명</th>
                    <th>작업 상태</th>
                    <th>작업 유형</th>
                    <th>작업 등록일</th>
                    <th>시작 지점</th>
                    <th>종료 지점</th>
                    <th>담당자</th>
                  </tr>
                </thead>
                <tbody>
                  {device.currentTask.map((task, idx) => (
                    <tr key={`${task.taskId}-${idx}`}>
                      <td>{task.taskId}</td>
                      <td>
                        <span
                          className={`robot-info__task-state robot-info__task-state--${task.state}`}
                        >
                          {task.state}
                        </span>
                      </td>
                      <td>{task.type}</td>
                      <td>{task.createTime}</td>
                      <td>{task.start}</td>
                      <td>{task.end}</td>
                      <td>{task.oper}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section> */}
      </div>
    </Modal>
  );
}
