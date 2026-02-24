"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { IconButton } from "../ui/IconButton";
import { AlarmSearchPopup } from "./AlarmSearchPopup";
import { ALARM_ERROR_TYPE_LABELS } from "@/lib/constants/alarm";
import { getTodayAlarms } from "@/lib/mock/alarmSearch";
import type { AlarmSearchItem } from "@/lib/types/alarm-search";

function speakAlarm(alarm: AlarmSearchItem): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;

  window.speechSynthesis.cancel();

  const errorLabel = ALARM_ERROR_TYPE_LABELS[alarm.errorType];
  const text = `${alarm.robotSn} ${errorLabel} 발생했으니 확인부탁드립니다.`;

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "ko-KR";
  utterance.rate = 1.0;
  utterance.pitch = 1.0;

  const voices = window.speechSynthesis.getVoices();
  const koreanVoice = voices.find((v) => v.lang.startsWith("ko"));
  if (koreanVoice) {
    utterance.voice = koreanVoice;
  }

  window.speechSynthesis.speak(utterance);
}

type AlarmPopoverProps = {
  iconSrc?: string;
};

export function AlarmPopover({
  iconSrc = "/icon/Icon_v2 (41).png",
}: AlarmPopoverProps = {}) {
  const [open, setOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [soundOn, setSoundOn] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [readAlarmIds, setReadAlarmIds] = useState<Set<string>>(new Set());
  const triggerRef = useRef<HTMLDivElement>(null);

  const todayAlarms = useMemo(() => getTodayAlarms(), []);

  const activeAlarmCount = useMemo(
    () => todayAlarms.filter((a) => a.status === "Warning" && !readAlarmIds.has(a.id)).length,
    [todayAlarms, readAlarmIds]
  );

  const hasGlobalNeonAlert = todayAlarms.some(
    (a) => a.status === "Warning" && !readAlarmIds.has(a.id)
  );

  const showNeon = hasGlobalNeonAlert;

  // Preload voices for TTS
  useEffect(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.getVoices();
      const handler = () => window.speechSynthesis.getVoices();
      window.speechSynthesis.addEventListener("voiceschanged", handler);
      return () =>
        window.speechSynthesis.removeEventListener("voiceschanged", handler);
    }
  }, []);

  useEffect(() => {
    document.body.removeAttribute("data-alarm-urgent");
    if (showNeon) {
      document.body.setAttribute("data-alarm-neon", "true");
    } else {
      document.body.removeAttribute("data-alarm-neon");
    }
    return () => {
      document.body.removeAttribute("data-alarm-neon");
    };
  }, [showNeon]);

  const handleClose = useCallback(() => {
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        handleClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open, handleClose]);

  const displayAlarms = useMemo(() => {
    let filtered = todayAlarms.filter((a) => !readAlarmIds.has(a.id));
    if (keyword) {
      const k = keyword.toLowerCase();
      filtered = filtered.filter(
        (a) =>
          a.message.toLowerCase().includes(k) ||
          a.code.toLowerCase().includes(k) ||
          a.robotSn.toLowerCase().includes(k)
      );
    }
    return filtered;
  }, [todayAlarms, readAlarmIds, keyword]);

  const noAlarms = displayAlarms.length === 0;

  const handleOpenSearch = () => {
    if (todayAlarms.length === 0) return;
    setOpen(false);
    setSearchOpen(true);
  };

  const handleReadAlarm = useCallback((id: string) => {
    setReadAlarmIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const handleReadAll = useCallback(() => {
    setReadAlarmIds(new Set(todayAlarms.map((a) => a.id)));
  }, [todayAlarms]);

  return (
    <>
      <div className="alarm-trigger" ref={triggerRef}>
        <IconButton
          className="alarm-trigger__btn"
          variant="ghost"
          aria-label="Open alarms"
          onClick={() => {
            setOpen((v) => !v);
          }}
        >
          <Image
            src={iconSrc}
            alt=""
            width={20}
            height={20}
            className="alarm-trigger__icon"
          />
        </IconButton>
        {activeAlarmCount > 0 ? (
          <span className="alarm-badge alarm-badge--error">
            {activeAlarmCount > 99 ? "99+" : activeAlarmCount}
          </span>
        ) : null}

        {open ? (
          <div className="alarm-popover">
            <div className="alarm-popover__toolbar">
              <div className="alarm-popover__toolbar-row">
                <input
                  type="text"
                  className="alarm-popover__search-input"
                  placeholder="오류 메시지, 오류코드, 로봇 SN 검색"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                />
                <IconButton
                  className="alarm-popover__toolbar-btn"
                  variant="ghost"
                  aria-label="검색"
                >
                  <img
                    src="/icon/search.png"
                    alt=""
                    className="alarm-popover__search-icon"
                  />
                </IconButton>
              </div>
              <div className="alarm-popover__toolbar-row">
                <button
                  type="button"
                  className={`alarm-popover__action-btn${noAlarms ? " alarm-popover__action-btn--disabled" : ""}`}
                  onClick={() => { if (!noAlarms) handleReadAll(); }}
                  aria-disabled={noAlarms}
                >
                  전체 읽음
                </button>
                <button
                  type="button"
                  className={`alarm-popover__action-btn${todayAlarms.length === 0 ? " alarm-popover__action-btn--disabled" : ""}`}
                  onClick={handleOpenSearch}
                  aria-disabled={todayAlarms.length === 0}
                >
                  알림 이력
                </button>
                <IconButton
                  className={`alarm-popover__toolbar-btn${noAlarms ? " alarm-popover__toolbar-btn--disabled" : ""}`}
                  variant="ghost"
                  aria-label={soundOn ? "Mute alarm sound" : "Enable alarm sound"}
                  aria-disabled={noAlarms}
                  onClick={() => { if (!noAlarms) setSoundOn((v) => !v); }}
                >
                  <img
                    src={
                      soundOn ? "/icon/sound-btn.png" : "/icon/sound-btn-off.png"
                    }
                    alt={soundOn ? "Sound on" : "Sound off"}
                    className="alarm-popover__sound-icon"
                  />
                </IconButton>
              </div>
            </div>
            <div className="alarm-popover__list">
              {displayAlarms.length === 0 ? (
                <div className="alarm-popover__empty">
                  오늘 발생한 알람이 없습니다.
                </div>
              ) : (
                displayAlarms.map((alarm) => {
                  const errorLabel =
                    ALARM_ERROR_TYPE_LABELS[alarm.errorType];
                  const severity =
                    alarm.status === "Warning" ? "warning" : "info";

                  return (
                    <div
                      key={alarm.id}
                      className={`alarm-item alarm-item--severity-${severity}`}
                    >
                      <div className="alarm-item__header">
                        <span
                          className={`alarm-item__code-severity alarm-item__severity--${severity}`}
                        >
                          [{alarm.code}] {errorLabel}
                        </span>
                      </div>
                      <p className="alarm-item__message">
                        [{alarm.robotSn}] [{errorLabel}] 발생했으니
                        확인부탁드립니다.
                      </p>
                      <div className="alarm-item__footer">
                        <span className="alarm-item__timestamp">
                          {alarm.timestamp}
                        </span>
                        <div className="alarm-item__footer-actions">
                          <button
                            type="button"
                            className="alarm-item__read-btn"
                            aria-label="읽음"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleReadAlarm(alarm.id);
                            }}
                          >
                            읽음
                          </button>
                          <button
                            type="button"
                            className={`alarm-item__tts-btn${!soundOn ? " alarm-item__tts-btn--disabled" : ""}`}
                            aria-label="알람 읽기"
                            aria-disabled={!soundOn}
                            onClick={(e) => {
                              e.stopPropagation();
                              if (soundOn) speakAlarm(alarm);
                            }}
                          >
                            <img
                              src={soundOn ? "/icon/sound-btn.png" : "/icon/sound-btn-off.png"}
                              alt={soundOn ? "Sound on" : "Sound off"}
                              className="alarm-item__tts-icon"
                            />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        ) : null}
      </div>

      {searchOpen ? (
        <AlarmSearchPopup onClose={() => setSearchOpen(false)} />
      ) : null}
    </>
  );
}
