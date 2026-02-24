"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MonthYearPicker } from "./MonthYearPicker";
import type { DateRangePickerProps } from "@/lib/types/tasks";
import "./DateRangePicker.css";

const DAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"];

function toDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function todayStr(): string {
  return toDateStr(new Date());
}

type CalendarDay = {
  date: string;
  day: number;
  outside: boolean;
};

function buildCalendarGrid(year: number, month: number): CalendarDay[] {
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrev = new Date(year, month, 0).getDate();

  const days: CalendarDay[] = [];

  for (let i = firstDay - 1; i >= 0; i--) {
    const d = daysInPrev - i;
    const dt = new Date(year, month - 1, d);
    days.push({ date: toDateStr(dt), day: d, outside: true });
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dt = new Date(year, month, d);
    days.push({ date: toDateStr(dt), day: d, outside: false });
  }

  const remaining = 42 - days.length;
  for (let d = 1; d <= remaining; d++) {
    const dt = new Date(year, month + 1, d);
    days.push({ date: toDateStr(dt), day: d, outside: true });
  }

  return days;
}

export function DateRangePicker({ startDate, endDate, onChange }: DateRangePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [viewYear, setViewYear] = useState(() => new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState(() => new Date().getMonth());
  const [tempStart, setTempStart] = useState<string | null>(startDate);
  const [tempEnd, setTempEnd] = useState<string | null>(endDate);
  const [showMyPicker, setShowMyPicker] = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setShowMyPicker(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [isOpen]);

  const handleOpen = useCallback(() => {
    setTempStart(startDate);
    setTempEnd(endDate);
    setShowMyPicker(false);
    if (startDate) {
      const d = new Date(startDate);
      setViewYear(d.getFullYear());
      setViewMonth(d.getMonth());
    } else {
      setViewYear(new Date().getFullYear());
      setViewMonth(new Date().getMonth());
    }
    setIsOpen(true);
  }, [startDate, endDate]);

  const handleDayClick = useCallback(
    (dateStr: string) => {
      if (!tempStart || tempEnd) {
        setTempStart(dateStr);
        setTempEnd(null);
      } else {
        let s = tempStart;
        let e = dateStr;
        if (e < s) [s, e] = [e, s];
        setTempStart(s);
        setTempEnd(e);
      }
    },
    [tempStart, tempEnd]
  );

  const handleToday = useCallback(() => {
    const t = todayStr();
    setTempStart(t);
    setTempEnd(t);
    const now = new Date();
    setViewYear(now.getFullYear());
    setViewMonth(now.getMonth());
  }, []);

  const handleDone = useCallback(() => {
    if (tempStart && tempEnd) {
      onChange(tempStart, tempEnd);
    } else if (tempStart) {
      onChange(tempStart, tempStart);
    }
    setIsOpen(false);
    setShowMyPicker(false);
  }, [tempStart, tempEnd, onChange]);

  const handleClear = useCallback(() => {
    setTempStart(null);
    setTempEnd(null);
    onChange(null, null);
    setIsOpen(false);
    setShowMyPicker(false);
  }, [onChange]);

  const prevMonth = () => {
    if (viewMonth === 0) {
      setViewYear((y) => y - 1);
      setViewMonth(11);
    } else {
      setViewMonth((m) => m - 1);
    }
  };

  const nextMonth = () => {
    if (viewMonth === 11) {
      setViewYear((y) => y + 1);
      setViewMonth(0);
    } else {
      setViewMonth((m) => m + 1);
    }
  };

  const days = buildCalendarGrid(viewYear, viewMonth);
  const today = todayStr();

  const displayValue =
    startDate && endDate
      ? `${startDate} to ${endDate}`
      : startDate
        ? startDate
        : "";

  function getDayClass(dateStr: string, outside: boolean): string {
    const classes = ["drp__day"];
    if (outside) classes.push("drp__day--outside");
    if (dateStr === today) classes.push("drp__day--today");
    if (dateStr === tempStart) classes.push("drp__day--start");
    if (dateStr === tempEnd) classes.push("drp__day--end");
    if (tempStart && tempEnd && dateStr > tempStart && dateStr < tempEnd) {
      classes.push("drp__day--in-range");
    }
    return classes.join(" ");
  }

  return (
    <div className="drp" ref={wrapperRef}>
      <input
        type="text"
        className="drp__input"
        readOnly
        placeholder="날짜 범위를 선택하세요."
        value={displayValue}
        onClick={handleOpen}
      />

      {isOpen && (
        <div className="drp__popup">
          <div className="drp__header">
            <button type="button" className="drp__nav-btn" onClick={prevMonth}>
              &lt;
            </button>
            <button
              type="button"
              className="drp__header-label"
              onClick={() => setShowMyPicker(true)}
            >
              {viewYear} / {String(viewMonth + 1).padStart(2, "0")}
            </button>
            <button type="button" className="drp__nav-btn" onClick={nextMonth}>
              &gt;
            </button>
          </div>

          <div className="drp__weekdays">
            {DAY_LABELS.map((d) => (
              <span key={d} className="drp__weekday">
                {d}
              </span>
            ))}
          </div>

          <div className="drp__grid">
            {days.map((d) => (
              <button
                key={d.date}
                type="button"
                className={getDayClass(d.date, d.outside)}
                onClick={() => handleDayClick(d.date)}
              >
                {d.day}
              </button>
            ))}
          </div>

          <div className="drp__footer">
            <button type="button" className="btn" onClick={handleClear}>
              초기화
            </button>
            <button type="button" className="btn" onClick={handleToday}>
              오늘
            </button>
            <button type="button" className="btn btn--primary" onClick={handleDone}>
              확인
            </button>
          </div>

          {showMyPicker && (
            <MonthYearPicker
              year={viewYear}
              month={viewMonth}
              onApply={(y, m) => {
                setViewYear(y);
                setViewMonth(m);
                setShowMyPicker(false);
              }}
              onCancel={() => setShowMyPicker(false)}
            />
          )}
        </div>
      )}
    </div>
  );
}
