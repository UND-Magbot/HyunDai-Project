"use client";

import { useState, useEffect, useCallback } from "react";
import { Modal } from "../Modal";
import { DESTINATION_OPTIONS, ACTION_TYPES } from "@/lib/mock/customTasks";
import type { AddStepModalProps, StepFormState, CustomTaskStep } from "@/lib/types/custom-tasks";
import "./AddStepModal.css";

const INITIAL_FORM: StepFormState = {
  actionType: "",
  destination: "",
  audio: "",
  waitTime: "",
};

export function AddStepModal({
  open,
  onClose,
  onSave,
  editStep,
  nextNum,
}: AddStepModalProps) {
  const [form, setForm] = useState<StepFormState>({ ...INITIAL_FORM });
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      if (editStep) {
        setForm({
          actionType: editStep.actionType,
          destination: editStep.destination,
          audio: editStep.audio ?? "",
          waitTime: editStep.waitTime?.toString() ?? "",
        });
      } else {
        setForm({ ...INITIAL_FORM });
      }
      setErrors({});
    }
  }, [open, editStep]);

  const updateField = <K extends keyof StepFormState>(
    key: K,
    value: StepFormState[K]
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
    if (!form.actionType) newErrors.actionType = "ActionType is required";
    if (!form.destination) newErrors.destination = "Destination is required";
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [form]);

  const handleConfirm = useCallback(() => {
    if (!validate()) return;
    const step: CustomTaskStep = {
      id: editStep?.id ?? crypto.randomUUID(),
      num: editStep?.num ?? nextNum,
      destination: form.destination,
      actionType: form.actionType,
      audio: form.audio || undefined,
      waitTime: form.waitTime ? parseInt(form.waitTime, 10) : undefined,
    };
    onSave(step);
    onClose();
  }, [validate, editStep, nextNum, form, onSave, onClose]);

  const handleClose = useCallback(() => {
    setForm({ ...INITIAL_FORM });
    setErrors({});
    onClose();
  }, [onClose]);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={editStep ? "Edit Step" : "Add Step"}
      width="480px"
    >
      <div className="add-step">
        <div className="add-step__field">
          <span className="add-step__label">
            ActionType <span className="add-step__required">*</span>
          </span>
          <select
            className={`add-step__select${!form.actionType ? " add-step__select--placeholder" : ""}${errors.actionType ? " add-step__select--error" : ""}`}
            value={form.actionType}
            onChange={(e) => updateField("actionType", e.target.value)}
          >
            <option value="" disabled hidden>
              Please Choose
            </option>
            {ACTION_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          {errors.actionType && (
            <span className="add-step__error">{errors.actionType}</span>
          )}
        </div>

        <div className="add-step__field">
          <span className="add-step__label">
            Destination <span className="add-step__required">*</span>
          </span>
          <select
            className={`add-step__select${!form.destination ? " add-step__select--placeholder" : ""}${errors.destination ? " add-step__select--error" : ""}`}
            value={form.destination}
            onChange={(e) => updateField("destination", e.target.value)}
          >
            <option value="" disabled hidden>
              Please Choose
            </option>
            {DESTINATION_OPTIONS.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.floor})
              </option>
            ))}
          </select>
          {errors.destination && (
            <span className="add-step__error">{errors.destination}</span>
          )}
        </div>

        <div className="add-step__field">
          <span className="add-step__label">Audio</span>
          <input
            type="text"
            className="add-step__input"
            placeholder="Optional audio file"
            value={form.audio}
            onChange={(e) => updateField("audio", e.target.value)}
          />
        </div>

        <div className="add-step__field">
          <span className="add-step__label">WaitTime (seconds)</span>
          <input
            type="number"
            className="add-step__input"
            placeholder="Optional"
            value={form.waitTime}
            onChange={(e) => updateField("waitTime", e.target.value)}
          />
        </div>

        <div className="add-step__footer">
          <button
            type="button"
            className="add-step__btn add-step__btn--cancel"
            onClick={handleClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="add-step__btn add-step__btn--confirm"
            onClick={handleConfirm}
          >
            Confirm
          </button>
        </div>
      </div>
    </Modal>
  );
}
