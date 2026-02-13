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
    if (!form.taskName.trim()) newErrors.taskName = "TaskName is required";
    if (!form.business) newErrors.business = "Business is required";
    if (
      isNaN(form.speed) ||
      form.speed < SPEED_MIN ||
      form.speed > SPEED_MAX ||
      form.speed % SPEED_STEP !== 0
    ) {
      newErrors.speed = `Speed must be ${SPEED_MIN}~${SPEED_MAX}, multiple of ${SPEED_STEP}`;
    }
    if (form.steps.length === 0) {
      newErrors.steps = "At least one step is required";
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
      title={editTask ? "Edit Task" : "Add Task"}
      width="720px"
    >
      <div className="ct-modal">
        {/* ─── Task Info Section ─── */}
        <section className="ct-modal__section">
          <h3 className="ct-modal__section-title">Task Info</h3>
          <div className="ct-modal__params">
            {/* TaskName */}
            <div className="ct-modal__field">
              <span className="ct-modal__label">
                TaskName <span className="ct-modal__required">*</span>
              </span>
              <input
                type="text"
                className={`ct-modal__input${errors.taskName ? " ct-modal__input--error" : ""}`}
                placeholder="Enter task name"
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
                Business <span className="ct-modal__required">*</span>
              </span>
              <select
                className={`ct-modal__select${!form.business ? " ct-modal__select--placeholder" : ""}${errors.business ? " ct-modal__select--error" : ""}`}
                value={form.business}
                onChange={(e) =>
                  updateField("business", e.target.value as BusinessType | "")
                }
              >
                <option value="" disabled hidden>
                  Please Choose
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
              <span className="ct-modal__label">RCS Tasks</span>
              <select
                className="ct-modal__select"
                value={form.rcsTasks ? "YES" : "NO"}
                onChange={(e) =>
                  updateField("rcsTasks", e.target.value === "YES")
                }
              >
                <option value="YES">YES</option>
                <option value="NO">NO</option>
              </select>
            </div>

            {/* Return + Speed — only visible when RCS Tasks is NO, displayed in one row */}
            {!form.rcsTasks && (
            <>
              <div className="ct-modal__field">
                <span className="ct-modal__label">Return</span>
                <select
                  className="ct-modal__select"
                  value={form.returnTask ? "YES" : "NO"}
                  onChange={(e) =>
                    updateField("returnTask", e.target.value === "YES")
                  }
                >
                  <option value="YES">YES</option>
                  <option value="NO">NO</option>
                </select>
              </div>

              <div className="ct-modal__field">
                <span className="ct-modal__label">
                  Speed <span className="ct-modal__required">*</span>
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
            <h3 className="ct-modal__section-title">Steps</h3>
            <button
              type="button"
              className="ct-modal__add-step-btn"
              onClick={handleAddStep}
            >
              + Add Step
            </button>
          </div>

          <div
            className={`ct-modal__step-table-wrapper${errors.steps ? " ct-modal__step-table-wrapper--error" : ""}`}
          >
            <table className="ct-modal__step-table">
              <thead>
                <tr>
                  <th>Num</th>
                  <th>Destination</th>
                  <th>ActionType</th>
                  <th>Operation</th>
                </tr>
              </thead>
              <tbody>
                {form.steps.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="ct-modal__step-empty">
                      No steps added
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
                            Edit
                          </button>
                          <button
                            type="button"
                            className="ct-modal__step-delete-btn"
                            onClick={() => handleDeleteStep(step.id)}
                          >
                            Delete
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
            Cancel
          </button>
          <button
            type="button"
            className="ct-modal__btn ct-modal__btn--confirm"
            onClick={handleConfirm}
          >
            Confirm
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
