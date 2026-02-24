"use client";

import { useState, useEffect, useCallback } from "react";
import { Modal } from "../Modal";
import { DESTINATION_OPTIONS, ACTION_TYPES } from "@/lib/mock/customTasks";
import type {
  AddStepModalProps,
  StepFormState,
  CustomTaskStep,
} from "@/lib/types/custom-tasks";
import "./AddStepModal.css";

const VOLUME_MIN = 0;
const VOLUME_MAX = 100;
const VOLUME_STEP = 1;
const VOLUME_DEFAULT = 50;

const INITIAL_FORM: StepFormState = {
  actionType: "",
  destination: "",
  audio: "",
  volume: String(VOLUME_DEFAULT),
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
          volume: editStep.volume?.toString() ?? String(VOLUME_DEFAULT),
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

    if (!form.actionType) newErrors.actionType = "동작 유형을 선택해주세요";
    if (!form.destination) newErrors.destination = "목적지를 선택해주세요";

    const volumeValue = Number(form.volume);
    if (
      form.volume === "" ||
      !Number.isFinite(volumeValue) ||
      !Number.isInteger(volumeValue) ||
      volumeValue < VOLUME_MIN ||
      volumeValue > VOLUME_MAX
    ) {
      newErrors.volume = "볼륨은 0에서 100 사이의 정수여야 합니다.";
    }

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
      volume: parseInt(form.volume, 10),
    };

    onSave(step);
    onClose();
  }, [validate, editStep, nextNum, form, onSave, onClose]);

  const handleClose = useCallback(() => {
    setForm({ ...INITIAL_FORM });
    setErrors({});
    onClose();
  }, [onClose]);

  const handleVolumeChange = (raw: string) => {
    updateField("volume", raw);
  };

  const handleVolumeStep = (delta: number) => {
    const current = Number(form.volume);
    const base = Number.isInteger(current) ? current : VOLUME_DEFAULT;
    const next = Math.min(VOLUME_MAX, Math.max(VOLUME_MIN, base + delta));
    updateField("volume", String(next));
  };

  const currentVolume = Number(form.volume);
  const isCurrentVolumeInteger = Number.isInteger(currentVolume);
  const canDecreaseVolume =
    !isCurrentVolumeInteger || currentVolume > VOLUME_MIN;
  const canIncreaseVolume =
    !isCurrentVolumeInteger || currentVolume < VOLUME_MAX;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={editStep ? "스텝 수정" : "스텝 추가"}
      width="480px"
    >
      <div className="add-step">
        <div className="add-step__field">
          <span className="add-step__label">
            동작 유형 <span className="add-step__required">*</span>
          </span>
          <select
            className={`add-step__select${
              !form.actionType ? " add-step__select--placeholder" : ""
            }${errors.actionType ? " add-step__select--error" : ""}`}
            value={form.actionType}
            onChange={(e) => updateField("actionType", e.target.value)}
          >
            <option value="" disabled hidden>
              동작 유형을 선택해주세요.
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
            목적지 <span className="add-step__required">*</span>
          </span>
          <select
            className={`add-step__select${
              !form.destination ? " add-step__select--placeholder" : ""
            }${errors.destination ? " add-step__select--error" : ""}`}
            value={form.destination}
            onChange={(e) => updateField("destination", e.target.value)}
          >
            <option value="" disabled hidden>
              목적지를 선택해주세요.
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
          <span className="add-step__label">오디오</span>
          <input
            type="text"
            className="add-step__input"
            placeholder="선택 입력(오디오 파일)"
            value={form.audio}
            onChange={(e) => updateField("audio", e.target.value)}
          />
        </div>

        <div className="add-step__field">
          <span className="add-step__label">볼륨</span>
          <div
            className={`add-step__stepper${
              errors.volume ? " add-step__stepper--error" : ""
            }`}
          >
            <button
              type="button"
              className="add-step__stepper-btn"
              onClick={() => handleVolumeStep(-VOLUME_STEP)}
              disabled={!canDecreaseVolume}
            >
              -
            </button>
            <input
              type="number"
              className="add-step__stepper-input"
              min={VOLUME_MIN}
              max={VOLUME_MAX}
              step={VOLUME_STEP}
              value={form.volume}
              onChange={(e) => handleVolumeChange(e.target.value)}
            />
            <button
              type="button"
              className="add-step__stepper-btn"
              onClick={() => handleVolumeStep(VOLUME_STEP)}
              disabled={!canIncreaseVolume}
            >
              +
            </button>
          </div>
          {errors.volume && (
            <span className="add-step__error">{errors.volume}</span>
          )}
        </div>

        <div className="add-step__footer">
          <button
            type="button"
            className="add-step__btn add-step__btn--cancel"
            onClick={handleClose}
          >
            취소
          </button>
          <button
            type="button"
            className="add-step__btn add-step__btn--confirm"
            onClick={handleConfirm}
          >
            확인
          </button>
        </div>
      </div>
    </Modal>
  );
}
