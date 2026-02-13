"use client";

import { useState, useCallback, useEffect } from "react";
import { Modal } from "../Modal";
import { mockBusinesses } from "@/lib/mock/robotDevices";
import { SITE_OPTIONS } from "@/lib/mock/cruiseRoutes";
import type {
  CruiseRouteModalProps,
  CruiseRouteFormState,
  CruiseRoute,
  CruiseRouteSite,
} from "@/lib/types/cruise-route";
import "./CruiseRouteModal.css";

function formatDateTime() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

const INITIAL_FORM: CruiseRouteFormState = {
  routeName: "",
  businessId: "",
  sites: [],
};

export function CruiseRouteModal({
  open,
  onClose,
  onSave,
  editRoute,
}: CruiseRouteModalProps) {
  const [form, setForm] = useState<CruiseRouteFormState>({ ...INITIAL_FORM });
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      if (editRoute) {
        setForm({
          routeName: editRoute.routeName,
          businessId: editRoute.businessId,
          sites: editRoute.sites.map((s) => ({ ...s })),
        });
      } else {
        setForm({ ...INITIAL_FORM, sites: [] });
      }
      setErrors({});
    }
  }, [open, editRoute]);

  const updateField = <K extends keyof CruiseRouteFormState>(
    key: K,
    value: CruiseRouteFormState[K]
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
    if (!form.routeName.trim()) newErrors.routeName = "Route Name is required";
    if (!form.businessId) newErrors.businessId = "Business is required";
    if (form.sites.length === 0) newErrors.sites = "At least one site is required";
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [form]);

  const handleSiteToggle = useCallback(
    (site: CruiseRouteSite, checked: boolean) => {
      setForm((prev) => {
        let nextSites: CruiseRouteSite[];
        if (checked) {
          nextSites = [...prev.sites, { ...site }];
        } else {
          // Remove last occurrence of this site
          const lastIdx = prev.sites.map((s) => s.id).lastIndexOf(site.id);
          if (lastIdx >= 0) {
            nextSites = prev.sites.filter((_, i) => i !== lastIdx);
          } else {
            nextSites = prev.sites;
          }
        }
        return { ...prev, sites: nextSites };
      });
      setErrors((prev) => {
        const next = { ...prev };
        delete next.sites;
        return next;
      });
    },
    []
  );

  const handleConfirm = useCallback(() => {
    if (!validate()) return;
    const business = mockBusinesses.find((b) => b.id === form.businessId);
    const route: CruiseRoute = {
      id: editRoute?.id ?? crypto.randomUUID(),
      routeName: form.routeName,
      businessId: form.businessId,
      businessName: business?.name ?? "",
      sites: form.sites,
      siteCount: form.sites.length,
      createTime: editRoute?.createTime ?? formatDateTime(),
    };
    onSave(route);
    onClose();
  }, [validate, editRoute, form, onSave, onClose]);

  const handleClose = useCallback(() => {
    setForm({ ...INITIAL_FORM, sites: [] });
    setErrors({});
    onClose();
  }, [onClose]);

  const isSiteSelected = (siteId: string) =>
    form.sites.some((s) => s.id === siteId);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={editRoute ? "Edit Cruise Route" : "Cruise Route"}
      width="720px"
    >
      <div className="cr-modal">
        {/* ─── Basic Setting ─── */}
        <section className="cr-modal__section">
          <h3 className="cr-modal__section-title">Basic Setting</h3>
          <div className="cr-modal__fields">
            {/* Route Name */}
            <div className="cr-modal__field">
              <span className="cr-modal__label">
                Route Name <span className="cr-modal__required">*</span>
              </span>
              <input
                type="text"
                className={`cr-modal__input${errors.routeName ? " cr-modal__input--error" : ""}`}
                placeholder="Enter route name"
                value={form.routeName}
                onChange={(e) => updateField("routeName", e.target.value)}
              />
              {errors.routeName && (
                <span className="cr-modal__error">{errors.routeName}</span>
              )}
            </div>

            {/* Select Business */}
            <div className="cr-modal__field">
              <span className="cr-modal__label">
                Select Business <span className="cr-modal__required">*</span>
              </span>
              <select
                className={`cr-modal__select${!form.businessId ? " cr-modal__select--placeholder" : ""}${errors.businessId ? " cr-modal__select--error" : ""}`}
                value={form.businessId}
                onChange={(e) => updateField("businessId", e.target.value)}
              >
                <option value="" disabled hidden>
                  Please Choose
                </option>
                {mockBusinesses.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              {errors.businessId && (
                <span className="cr-modal__error">{errors.businessId}</span>
              )}
            </div>
          </div>
        </section>

        {/* ─── Selected Sites ─── */}
        {form.businessId && (
          <>
            <section className="cr-modal__section">
              <h3 className="cr-modal__section-title">Selected Sites</h3>
              <div
                className={`cr-modal__selected-sites${errors.sites ? " cr-modal__selected-sites--error" : ""}`}
              >
                {form.sites.length === 0 ? (
                  <span className="cr-modal__no-sites">No sites selected</span>
                ) : (
                  form.sites.map((site, idx) => (
                    <span key={idx} className="cr-modal__site-flow">
                      <span className="cr-modal__site-badge">{site.name}</span>
                      {idx < form.sites.length - 1 && (
                        <span className="cr-modal__site-arrow">→</span>
                      )}
                    </span>
                  ))
                )}
              </div>
              {errors.sites && (
                <span className="cr-modal__error">{errors.sites}</span>
              )}
            </section>

            {/* ─── Select Site ─── */}
            <section className="cr-modal__section">
              <h3 className="cr-modal__section-title">Select Site</h3>
              <div className="cr-modal__site-groups">
                {SITE_OPTIONS.map((group) => (
                  <div key={group.floor} className="cr-modal__floor-group">
                    <h4 className="cr-modal__floor-title">{group.floor}</h4>
                    <div className="cr-modal__site-list">
                      {group.sites.map((site) => (
                        <label
                          key={site.id}
                          className="cr-modal__site-checkbox"
                        >
                          <input
                            type="checkbox"
                            checked={isSiteSelected(site.id)}
                            onChange={(e) =>
                              handleSiteToggle(
                                { id: site.id, name: site.name, floor: site.floor },
                                e.target.checked
                              )
                            }
                          />
                          <span className="cr-modal__site-name">
                            {site.name}
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {/* ─── Footer ─── */}
        <div className="cr-modal__footer">
          <button
            type="button"
            className="cr-modal__btn cr-modal__btn--cancel"
            onClick={handleClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="cr-modal__btn cr-modal__btn--confirm"
            onClick={handleConfirm}
          >
            Confirm
          </button>
        </div>
      </div>
    </Modal>
  );
}
