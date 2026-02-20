"use client";

import { useState, useCallback, useEffect } from "react";
import { Modal } from "../Modal";
import { AddStepModal } from "./AddStepModal";
import { BUSINESS_OPTIONS, DESTINATION_OPTIONS } from "@/lib/mock/customTasks";
import type {
  CustomTaskModalProps,
  CustomTaskFormState,
  CustomTaskStep,
  CustomTask,
  BusinessType,
} from "@/lib/types/custom-tasks";
import "./CustomTaskModal.css";

const SPEED_MIN = 40;
const SPEED_MAX = 120;
const SPEED_STEP = 10;

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

const INITIAL_FORM: CustomTaskFormState = {
  taskName: "",
  business: "",
  rcsTasks: false,
  returnTask: false,
  speed: 40,
  steps: [],
};

function getDestinationName(destId: string): string {
  const dest = DESTINATION_OPTIONS.find((d) => d.id === destId);
  return dest ? `${dest.name} (${dest.floor})` : destId;
}

export function CustomTaskModal({
  open,
  onClose,
  onSave,
  editTask,
}: CustomTaskModalProps) {
  const [form, setForm] = useState<CustomTaskFormState>({ ...INITIAL_FORM });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [stepModalOpen, setStepModalOpen] = useState(false);
  const [editStepData, setEditStepData] = useState<CustomTaskStep | null>(null);

  useEffect(() => {
    if (open) {
      if (editTask) {
        setForm({
          taskName: editTask.taskName,
          business: editTask.business,
          rcsTasks: editTask.rcsTasks,
          returnTask: editTask.returnTask,
          speed: editTask.speed,
          steps: editTask.steps.map((s) => ({ ...s })),
        });
      } else {
        setForm({ ...INITIAL_FORM, steps: [] });
      }
      setErrors({});
    }
  }, [open, editTask]);

  const updateField = <K extends keyof CustomTaskFormState>(
    key: K,
    value: CustomTaskFormState[K]
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {};
    if (!form.taskName.trim()) newErrors.taskName = "작업명을 입력하세요.";
    if (!form.business) newErrors.business = "고객사를 선택하세요.";
    if (
      isNaN(form.speed) ||
      form.speed < SPEED_MIN ||
      form.speed > SPEED_MAX ||
      form.speed % SPEED_STEP !== 0
    ) {
      newErrors.speed = `속도는 ${SPEED_MIN}~${SPEED_MAX} 범위의 ${SPEED_STEP} 단위여야 합니다.`;
    }
    if (form.steps.length === 0) {
      newErrors.steps = "스텝을 하나 이상 추가하세요.";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [form]);

  const handleStepSave = useCallback(
    (step: CustomTaskStep) => {
      setForm((prev) => {
        const idx = prev.steps.findIndex((s) => s.id === step.id);
        if (idx >= 0) {
          const next = [...prev.steps];
          next[idx] = step;
          return { ...prev, steps: next };
        }
        return { ...prev, steps: [...prev.steps, step] };
      });
      setErrors((prev) => {
        const next = { ...prev };
        delete next.steps;
        return next;
      });
    },
    []
  );

  const handleDeleteStep = useCallback((stepId: string) => {
    setForm((prev) => {
      const filtered = prev.steps
        .filter((s) => s.id !== stepId)
        .map((s, i) => ({ ...s, num: i + 1 }));
      return { ...prev, steps: filtered };
    });
  }, []);

  const handleEditStep = useCallback((step: CustomTaskStep) => {
    setEditStepData(step);
    setStepModalOpen(true);
  }, []);

  const handleAddStep = useCallback(() => {
    setEditStepData(null);
    setStepModalOpen(true);
  }, []);

  const handleConfirm = useCallback(() => {
    if (!validate()) return;
    const task: CustomTask = {
      id: editTask?.id ?? crypto.randomUUID(),
      taskName: form.taskName,
      business: form.business as BusinessType,
      rcsTasks: form.rcsTasks,
      returnTask: form.returnTask,
      speed: form.speed,
      steps: form.steps,
      createTime: editTask?.createTime ?? formatDateTime(),
    };
    onSave(task);
    onClose();
  }, [validate, editTask, form, onSave, onClose]);

  const handleClose = useCallback(() => {
    setForm({ ...INITIAL_FORM, steps: [] });
    setErrors({});
    onClose();
  }, [onClose]);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={editTask ? "작업 수정" : "작업 등록"}
      width="720px"
    >
      <div className="ct-modal">
        {/* ─── Task Info Section ─── */}
        <section className="ct-modal__section">
          <div className="ct-modal__params">
            {/* TaskName */}
            <div className="ct-modal__field">
              <span className="ct-modal__label">
                작업명 <span className="ct-modal__required">*</span>
              </span>
              <input
                type="text"
                className={`ct-modal__input${errors.taskName ? " ct-modal__input--error" : ""}`}
                placeholder="작업명을 입력해주세요."
                value={form.taskName}
                onChange={(e) => updateField("taskName", e.target.value)}
              />
              {errors.taskName && (
                <span className="ct-modal__error">{errors.taskName}</span>
              )}
            </div>

            {/* Business */}
            <div className="ct-modal__field">
              <span className="ct-modal__label">
                고객사 <span className="ct-modal__required">*</span>
              </span>
              <select
                className={`ct-modal__select${!form.business ? " ct-modal__select--placeholder" : ""}${errors.business ? " ct-modal__select--error" : ""}`}
                value={form.business}
                onChange={(e) =>
                  updateField("business", e.target.value as BusinessType | "")
                }
              >
                <option value="" disabled hidden>
                  고객사를 선택해주세요.
                </option>
                {BUSINESS_OPTIONS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
              {errors.business && (
                <span className="ct-modal__error">{errors.business}</span>
              )}
            </div>

            {/* RCS Tasks */}
            <div className="ct-modal__field ct-modal__field--full">
              <span className="ct-modal__label">RCS 작업</span>
              <select
                className="ct-modal__select"
                value={form.rcsTasks ? "YES" : "NO"}
                onChange={(e) =>
                  updateField("rcsTasks", e.target.value === "YES")
                }
              >
                <option value="YES">예</option>
                <option value="NO">아니오</option>
              </select>
            </div>

            {/* Return + Speed — only visible when RCS Tasks is NO, displayed in one row */}
            {!form.rcsTasks && (
            <>
              <div className="ct-modal__field">
                <span className="ct-modal__label">복귀 작업</span>
                <select
                  className="ct-modal__select"
                  value={form.returnTask ? "YES" : "NO"}
                  onChange={(e) =>
                    updateField("returnTask", e.target.value === "YES")
                  }
                >
                  <option value="YES">예</option>
                  <option value="NO">아니오</option>
                </select>
              </div>

              <div className="ct-modal__field">
                <span className="ct-modal__label">
                  속도 <span className="ct-modal__required">*</span>
                </span>
                <div
                  className={`ct-modal__stepper${errors.speed ? " ct-modal__stepper--error" : ""}`}
                >
                  <button
                    type="button"
                    className="ct-modal__stepper-btn"
                    disabled={form.speed <= SPEED_MIN}
                    onClick={() =>
                      updateField(
                        "speed",
                        Math.max(SPEED_MIN, form.speed - SPEED_STEP)
                      )
                    }
                  >
                    −
                  </button>
                  <input
                    type="number"
                    className="ct-modal__stepper-input"
                    value={form.speed}
                    onChange={(e) => {
                      const val =
                        e.target.value === ""
                          ? 0
                          : parseInt(e.target.value, 10);
                      if (!isNaN(val)) updateField("speed", val);
                    }}
                  />
                  <button
                    type="button"
                    className="ct-modal__stepper-btn"
                    disabled={form.speed >= SPEED_MAX}
                    onClick={() =>
                      updateField(
                        "speed",
                        Math.min(SPEED_MAX, form.speed + SPEED_STEP)
                      )
                    }
                  >
                    +
                  </button>
                </div>
                {errors.speed && (
                  <span className="ct-modal__error">{errors.speed}</span>
                )}
              </div>
            </>
            )}
          </div>
        </section>

        {/* ─── Steps Section ─── */}
        <section className="ct-modal__section">
          <div className="ct-modal__step-header">
            <h3 className="ct-modal__section-title">스텝</h3>
            <button
              type="button"
              className="ct-modal__add-step-btn"
              onClick={handleAddStep}
            >
              + 스텝 추가
            </button>
          </div>

          <div
            className={`ct-modal__step-table-wrapper${errors.steps ? " ct-modal__step-table-wrapper--error" : ""}`}
          >
            <table className="ct-modal__step-table">
              <thead>
                <tr>
                  <th>번호</th>
                  <th>목적지</th>
                  <th>동작 유형</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                {form.steps.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="ct-modal__step-empty">
                      추가된 스텝이 없습니다.
                    </td>
                  </tr>
                ) : (
                  form.steps.map((step) => (
                    <tr key={step.id}>
                      <td>{step.num}</td>
                      <td>{getDestinationName(step.destination)}</td>
                      <td>{step.actionType}</td>
                      <td>
                        <div className="ct-modal__step-actions">
                          <button
                            type="button"
                            className="ct-modal__step-edit-btn"
                            onClick={() => handleEditStep(step)}
                          >
                            수정
                          </button>
                          <button
                            type="button"
                            className="ct-modal__step-delete-btn"
                            onClick={() => handleDeleteStep(step.id)}
                          >
                            삭제
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {errors.steps && (
            <span className="ct-modal__error">{errors.steps}</span>
          )}
        </section>

        {/* ─── Footer ─── */}
        <div className="ct-modal__footer">
          <button
            type="button"
            className="ct-modal__btn ct-modal__btn--cancel"
            onClick={handleClose}
          >
            취소
          </button>
          <button
            type="button"
            className="ct-modal__btn ct-modal__btn--confirm"
            onClick={handleConfirm}
          >
            확인
          </button>
        </div>
      </div>

      <AddStepModal
        open={stepModalOpen}
        onClose={() => {
          setStepModalOpen(false);
          setEditStepData(null);
        }}
        onSave={handleStepSave}
        editStep={editStepData}
        nextNum={form.steps.length + 1}
      />
    </Modal>
  );
}
