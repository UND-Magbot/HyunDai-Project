"use client";

import { useState, useCallback, useMemo } from "react";
import { Modal } from "../Modal";
import { mockDevices } from "@/lib/mock/devices";
import { mockRoutes } from "@/lib/mock/routes";
import type {
  CreateTaskModalProps,
  CreateTaskFormState,
  CreateTaskPayload,
  TaskType,
  TaskMode,
} from "@/lib/types/tasks";
import "./CreateTaskModal.css";

const TASK_TYPES: TaskType[] = [
  "Jacking",
  "Transport",
  "Disinfect",
  "Park",
  "Charge",
];

const MODE_OPTIONS: { value: TaskMode; label: string }[] = [
  { value: "DRIVING", label: "Driving Along the Track" },
  { value: "STRICT_DRIVING", label: "Strict Driving Along the Track" },
];

const DETOUR_STEP = 0.4;
const DETOUR_MIN = 0;
const DETOUR_MAX = 2;
const SPEED_MIN = 40;
const SPEED_MAX = 120;

const INITIAL_FORM: CreateTaskFormState = {
  taskType: "",
  robot: "",
  maxSpeed: 40,
  mode: "",
  detourR: 0,
  cycles: 1,
  selectedRoutes: [],
};

type RouteTab = "sitepoint" | "routetask";

export function CreateTaskModal({ open, onClose }: CreateTaskModalProps) {
  const [form, setForm] = useState<CreateTaskFormState>({ ...INITIAL_FORM });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [routeTab, setRouteTab] = useState<RouteTab>("routetask");

  const onlineDevices = useMemo(
    () => mockDevices.filter((d) => d.power === "online"),
    []
  );

  const resetForm = useCallback(() => {
    setForm({ ...INITIAL_FORM });
    setErrors({});
    setRouteTab("routetask");
  }, []);

  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [resetForm, onClose]);

  const updateField = <K extends keyof CreateTaskFormState>(
    key: K,
    value: CreateTaskFormState[K]
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleRouteToggle = (routeId: string) => {
    setForm((prev) => {
      const selected = prev.selectedRoutes.includes(routeId)
        ? prev.selectedRoutes.filter((id) => id !== routeId)
        : [...prev.selectedRoutes, routeId];
      return { ...prev, selectedRoutes: selected };
    });
    setErrors((prev) => {
      const next = { ...prev };
      delete next.selectedRoutes;
      return next;
    });
  };

  const handleSelectAll = (checked: boolean) => {
    const allIds = checked ? mockRoutes.map((r) => r.id) : [];
    updateField("selectedRoutes", allIds);
  };

  const allSelected =
    mockRoutes.length > 0 &&
    mockRoutes.every((r) => form.selectedRoutes.includes(r.id));

  const roundDetour = (val: number): number => {
    return Math.round(val * 10) / 10;
  };

  const isDetourEnabled = form.mode === "DRIVING";

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!form.taskType) {
      newErrors.taskType = "작업 유형을 선택해 주세요.";
    }

    if (!form.mode) {
      newErrors.mode = "모드를 선택해 주세요.";
    }

    if (isNaN(form.maxSpeed) || form.maxSpeed < SPEED_MIN || form.maxSpeed > SPEED_MAX) {
      newErrors.maxSpeed = `최대 속도가 허용 범위(${SPEED_MIN}~${SPEED_MAX})를 벗어났습니다.`;
    }

    if (isDetourEnabled) {
      const validDetourValues = [0, 0.4, 0.8, 1.2, 1.6, 2.0];
      if (isNaN(form.detourR) || !validDetourValues.includes(roundDetour(form.detourR))) {
        newErrors.detourR = "유효하지 않은 우회 반경이 입력되었습니다.";
      }
    }

    if (isNaN(form.cycles) || form.cycles < 1 || !Number.isInteger(form.cycles)) {
      newErrors.cycles = "유효하지 않은 반복 횟수가 입력되었습니다.";
    }

    if (!form.robot) {
      newErrors.robot = "로봇을 선택해 주세요.";
    } else if (form.robot !== "Auto") {
      const device = mockDevices.find((d) => d.id === form.robot);
      if (device && device.power !== "online") {
        newErrors.robot = "선택한 로봇이 오프라인 상태입니다.";
      }
    }

    if (form.selectedRoutes.length === 0) {
      newErrors.selectedRoutes = "경로를 선택해 주세요.";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleConfirm = () => {
    if (!validate()) return;

    const payload: CreateTaskPayload = {
      taskType: form.taskType as TaskType,
      robot: form.robot,
      maxSpeed: form.maxSpeed,
      mode: form.mode as TaskMode,
      detourR: form.detourR,
      cycles: form.cycles,
      routes: form.selectedRoutes,
    };

    console.log("CreateTask Payload:", payload);
    handleClose();
  };

  return (
    <Modal open={open} onClose={handleClose} title="작업 생성" width="760px">
      <div className="create-task">
        {/* ─── Task Params ─── */}
        <section className="create-task__frist-box">
          <h3 className="create-task__section-title">작업 설정</h3>
          <div className="create-task__params">
            {/* Task Type */}
            <div className="create-task__field">
              <span className="create-task__label">작업 유형 <span className="create-task__required">*</span></span>
              <select
                className={`create-task__select ${!form.taskType ? "create-task__select--placeholder" : ""} ${errors.taskType ? "create-task__select--error" : ""}`}
                value={form.taskType}
                onChange={(e) =>
                  updateField("taskType", e.target.value as TaskType | "")
                }
              >
                <option value="" disabled hidden>
                  선택해주세요.
                </option>
                {TASK_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              {errors.taskType && (
                <span className="create-task__error">{errors.taskType}</span>
              )}
            </div>

            {/* Robot */}
            <div className="create-task__field">
              <span className="create-task__label">Robot <span className="create-task__required">*</span></span>
              <select
                className={`create-task__select ${!form.robot ? "create-task__select--placeholder" : ""} ${errors.robot ? "create-task__select--error" : ""}`}
                value={form.robot}
                onChange={(e) => updateField("robot", e.target.value)}
              >
                <option value="" disabled hidden>
                  선택해주세요.
                </option>
                <option value="Auto">Auto</option>
                {onlineDevices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              {errors.robot && (
                <span className="create-task__error">{errors.robot}</span>
              )}
            </div>

            {/* MaxSpeed */}
            <div className="create-task__field">
              <span className="create-task__label">MaxSpeed</span>
              <div
                className={`create-task__stepper ${errors.maxSpeed ? "create-task__stepper--error" : ""}`}
              >
                <button
                  type="button"
                  className="create-task__stepper-btn"
                  disabled={form.maxSpeed <= SPEED_MIN}
                  onClick={() =>
                    updateField(
                      "maxSpeed",
                      Math.max(SPEED_MIN, form.maxSpeed - 10)
                    )
                  }
                >
                  −
                </button>
                <input
                  type="number"
                  className="create-task__stepper-input"
                  value={form.maxSpeed}
                  onChange={(e) => {
                    const val = e.target.value === "" ? 0 : parseInt(e.target.value, 10);
                    if (!isNaN(val)) updateField("maxSpeed", val);
                  }}
                />
                <button
                  type="button"
                  className="create-task__stepper-btn"
                  disabled={form.maxSpeed >= SPEED_MAX}
                  onClick={() =>
                    updateField(
                      "maxSpeed",
                      Math.min(SPEED_MAX, form.maxSpeed + 10)
                    )
                  }
                >
                  +
                </button>
              </div>
              {errors.maxSpeed && (
                <span className="create-task__error">{errors.maxSpeed}</span>
              )}
            </div>

            {/* Mode */}
            <div className="create-task__field">
              <span className="create-task__label">Mode <span className="create-task__required">*</span></span>
              <select
                className={`create-task__select ${!form.mode ? "create-task__select--placeholder" : ""} ${errors.mode ? "create-task__select--error" : ""}`}
                value={form.mode}
                onChange={(e) =>
                  updateField("mode", e.target.value as TaskMode | "")
                }
              >
                <option value="" disabled hidden>
                  선택해주세요.
                </option>
                {MODE_OPTIONS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              {errors.mode && (
                <span className="create-task__error">{errors.mode}</span>
              )}
            </div>

            {/* DetourR */}
            <div className="create-task__field">
              <span className="create-task__label">DetourR</span>
              <div
                className={`create-task__stepper ${errors.detourR ? "create-task__stepper--error" : ""} ${!isDetourEnabled ? "create-task__stepper--disabled" : ""}`}
              >
                <button
                  type="button"
                  className="create-task__stepper-btn"
                  disabled={!isDetourEnabled || form.detourR <= DETOUR_MIN}
                  onClick={() =>
                    updateField(
                      "detourR",
                      roundDetour(
                        Math.max(DETOUR_MIN, form.detourR - DETOUR_STEP)
                      )
                    )
                  }
                >
                  −
                </button>
                <input
                  type="number"
                  className="create-task__stepper-input"
                  value={form.detourR}
                  disabled={!isDetourEnabled}
                  onChange={(e) => {
                    const val = e.target.value === "" ? 0 : parseFloat(e.target.value);
                    if (!isNaN(val)) updateField("detourR", val);
                  }}
                />
                <button
                  type="button"
                  className="create-task__stepper-btn"
                  disabled={!isDetourEnabled || form.detourR >= DETOUR_MAX}
                  onClick={() =>
                    updateField(
                      "detourR",
                      roundDetour(
                        Math.min(DETOUR_MAX, form.detourR + DETOUR_STEP)
                      )
                    )
                  }
                >
                  +
                </button>
              </div>
              {errors.detourR && (
                <span className="create-task__error">{errors.detourR}</span>
              )}
            </div>

            {/* Number of cycles */}
            <div className="create-task__field">
              <span className="create-task__label">Number of cycles</span>
              <div
                className={`create-task__stepper ${errors.cycles ? "create-task__stepper--error" : ""}`}
              >
                <button
                  type="button"
                  className="create-task__stepper-btn"
                  disabled={form.cycles <= 1}
                  onClick={() =>
                    updateField("cycles", Math.max(1, form.cycles - 1))
                  }
                >
                  −
                </button>
                <input
                  type="number"
                  className="create-task__stepper-input"
                  value={form.cycles}
                  onChange={(e) => {
                    const val = e.target.value === "" ? 0 : parseInt(e.target.value, 10);
                    if (!isNaN(val)) updateField("cycles", val);
                  }}
                />
                <button
                  type="button"
                  className="create-task__stepper-btn"
                  onClick={() => updateField("cycles", form.cycles + 1)}
                >
                  +
                </button>
              </div>
              {errors.cycles && (
                <span className="create-task__error">{errors.cycles}</span>
              )}
            </div>
          </div>
        </section>

        {/* ─── Route Section ─── */}
        <section>
          <h3 className="create-task__section-title">Route</h3>

          <div className="create-task__route-tabs">
            <button
              type="button"
              className={`create-task__route-tab ${routeTab === "sitepoint" ? "create-task__route-tab--active" : ""}`}
              onClick={() => setRouteTab("sitepoint")}
            >
              ChooseSitePoint
            </button>
            <button
              type="button"
              className={`create-task__route-tab ${routeTab === "routetask" ? "create-task__route-tab--active" : ""}`}
              onClick={() => setRouteTab("routetask")}
            >
              RouteTask
            </button>
          </div>

          {routeTab === "sitepoint" && (
            <div className="create-task__route-empty">
              SitePoint selection is not available yet.
            </div>
          )}

          {routeTab === "routetask" && (
            <div
              className={
                errors.selectedRoutes ? "create-task__route-error" : ""
              }
            >
              <table className="create-task__route-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        className="create-task__route-checkbox"
                        checked={allSelected}
                        onChange={(e) => handleSelectAll(e.target.checked)}
                      />
                    </th>
                    <th>Path Name</th>
                    <th>Robot</th>
                    <th>Description</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {mockRoutes.map((route) => (
                    <tr key={route.id}>
                      <td>
                        <input
                          type="checkbox"
                          className="create-task__route-checkbox"
                          checked={form.selectedRoutes.includes(route.id)}
                          onChange={() => handleRouteToggle(route.id)}
                        />
                      </td>
                      <td>{route.pathName}</td>
                      <td>{route.robotLabel}</td>
                      <td>{route.description}</td>
                      <td>
                        <button
                          type="button"
                          className="create-task__perform-btn"
                        >
                          Perform
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {errors.selectedRoutes && (
                <span className="create-task__error">
                  {errors.selectedRoutes}
                </span>
              )}
            </div>
          )}
        </section>

        {/* ─── Footer ─── */}
        <div className="create-task__footer">
          <button
            type="button"
            className="create-task__btn create-task__btn--cancel"
            onClick={handleClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="create-task__btn create-task__btn--confirm"
            onClick={handleConfirm}
          >
            Confirm
          </button>
        </div>
      </div>
    </Modal>
  );
}
