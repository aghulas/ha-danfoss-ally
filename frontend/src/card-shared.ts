/**
 * Fragments de rendu, icônes SVG et styles CSS partagés entre
 * `danfoss-ally-schedule-card` et `danfoss-ally-room-card`.
 */
import { type TemplateResult, css, html, nothing, svg } from "lit";

import { dayLabel, language, t } from "./localize";
import { DAY_KEYS, type Bar, dayBars, formatReadAt, isSetbackOnly } from "./schedule";
import type { DayKey, HassLike, Schedule, TimeRange, WriteJob } from "./types";
import { CARD_VERSION } from "./version";

export function renderSetpoints(
  hass: HassLike | undefined,
  comfort: number | null,
  setback: number | null,
): TemplateResult {
  const fmt = (v: number | null): string =>
    v === null ? "—" : t(hass, "degree", { value: v });
  return html`
    <div class="setpoints">
      <span class="chip comfort">
        <span class="swatch comfort"></span>${t(hass, "comfort")} ${fmt(comfort)}
      </span>
      <span class="chip setback">
        <span class="swatch setback"></span>${t(hass, "setback")} ${fmt(setback)}
      </span>
    </div>
  `;
}

export function renderScale(): TemplateResult {
  return html`
    <div class="scale" aria-hidden="true">
      <span>0 h</span><span>6 h</span><span>12 h</span><span>18 h</span><span>24 h</span>
    </div>
  `;
}

export function dayAriaLabel(
  hass: HassLike | undefined,
  day: DayKey,
  bars: Bar[],
  setbackOnly: boolean,
): string {
  const name = dayLabel(hass, day);
  if (setbackOnly) {
    return `${name} — ${t(hass, "setback_all_day")}`;
  }
  const parts = bars.map((bar) => t(hass, "range_label", { start: bar.start, end: bar.end }));
  return `${name} — ${parts.join(", ")}`;
}

export function renderReadDay(
  hass: HassLike | undefined,
  day: DayKey,
  ranges: TimeRange[],
): TemplateResult {
  const bars = dayBars(ranges);
  const label = dayAriaLabel(hass, day, bars, isSetbackOnly(ranges));
  return html`
    <div class="day">
      <span class="day-label">${dayLabel(hass, day)}</span>
      <div class="track" role="img" aria-label=${label}>
        ${bars.map(
          (bar) => html`
            <div
              class="bar"
              style="left:${bar.leftPct}%;width:${bar.widthPct}%"
              title=${t(hass, "range_label", { start: bar.start, end: bar.end })}
            ></div>
          `,
        )}
      </div>
    </div>
  `;
}

export function renderReadGrid(hass: HassLike | undefined, schedule: Schedule): TemplateResult {
  return html`
    <div class="grid">
      ${renderScale()}
      ${DAY_KEYS.map((day) => renderReadDay(hass, day, schedule.days[day] ?? []))}
    </div>
  `;
}

export function renderBadge(kind: string, icon: TemplateResult, label: string): TemplateResult {
  return html`
    <span class="badge ${kind}" title=${label} role="img" aria-label=${label}>${icon}</span>
  `;
}

export function jobStatusKind(status: WriteJob["status"]): string {
  switch (status) {
    case "applied":
      return "ok";
    case "partial":
      return "warn";
    case "failed":
      return "off";
    default:
      return "muted";
  }
}

export function renderJobBanner(
  hass: HassLike | undefined,
  job: WriteJob | null,
): TemplateResult | typeof nothing {
  if (!job) {
    return nothing;
  }
  const key = `job_status_${job.status}` as Parameters<typeof t>[1];
  return html`
    <div class="job">
      <span class="job-title">${t(hass, "job_heading")}</span>
      <span class="pill ${jobStatusKind(job.status)}">${t(hass, key)}</span>
    </div>
  `;
}

export function renderCardFooter(
  hass: HassLike | undefined,
  schedule: Schedule | null,
  canRefresh: boolean,
  refreshing: boolean,
  onRefresh: () => void,
): TemplateResult {
  const when = formatReadAt(schedule?.read_at, language(hass));
  const lastRead = when ? t(hass, "last_read", { when }) : t(hass, "never_read");
  return html`
    <div class="footer">
      <button
        class="refresh"
        @click=${onRefresh}
        ?disabled=${!canRefresh || refreshing}
        aria-label=${t(hass, "refresh")}
      >
        ${ICON_REFRESH}<span>${t(hass, "refresh")}</span>
      </button>
      <span class="read-at">${lastRead}</span>
      <span class="version">${t(hass, "version", { version: CARD_VERSION })}</span>
    </div>
  `;
}

export function renderReloadBanner(
  hass: HassLike | undefined,
  onReload: () => void,
): TemplateResult {
  return html`
    <div class="reload">
      <span>${t(hass, "reload_available")}</span>
      <button @click=${onReload}>${t(hass, "reload")}</button>
    </div>
  `;
}

export const cardSharedStyles = css`
  :host {
    display: block;
  }
  .content {
    padding: 0 16px 16px;
  }
  .titlebar {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    padding-top: 16px;
  }
  .room {
    font-size: 1.4rem;
    font-weight: 500;
    color: var(--primary-text-color);
  }
  .actions {
    display: inline-flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .hint {
    margin-top: 8px;
    color: var(--secondary-text-color);
    font-size: 0.9rem;
  }
  .banner {
    margin-top: 10px;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 0.85rem;
  }
  .banner.error {
    background: var(--error-color, #c62828);
    color: var(--text-primary-color, #fff);
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 16px;
    padding: 6px 12px;
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    font: inherit;
    font-size: 0.85rem;
  }
  .btn svg {
    width: 16px;
    height: 16px;
    fill: currentColor;
  }
  .btn:hover:not(:disabled) {
    background: var(--secondary-background-color, #f0f0f0);
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .btn.primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    border-color: transparent;
  }
  .btn.primary:hover:not(:disabled) {
    filter: brightness(0.95);
  }
  .btn.ghost {
    background: transparent;
  }
  .btn.tiny {
    padding: 4px 10px;
    font-size: 0.8rem;
  }
  .btn.icon {
    padding: 4px;
    border-radius: 8px;
  }
  .setpoints {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 8px 0;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 14px;
    font-size: 0.9rem;
    background: var(--secondary-background-color, #f0f0f0);
    color: var(--primary-text-color);
  }
  .swatch {
    width: 12px;
    height: 12px;
    border-radius: 3px;
  }
  .swatch.comfort,
  .bar {
    background: var(--danfoss-comfort-color, var(--primary-color, #03a9f4));
  }
  .swatch.setback {
    background: var(--danfoss-setback-color, var(--disabled-text-color, #9e9e9e));
  }
  .grid {
    margin: 8px 0 4px;
  }
  .scale {
    display: flex;
    justify-content: space-between;
    margin: 0 0 4px calc(2.6rem + 8px);
    color: var(--secondary-text-color);
    font-size: 0.7rem;
  }
  .day {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 3px 0;
  }
  .day-label {
    flex: 0 0 2.6rem;
    font-size: 0.8rem;
    color: var(--secondary-text-color);
  }
  .track {
    position: relative;
    flex: 1 1 auto;
    height: 16px;
    border-radius: 4px;
    background: var(--danfoss-track-color, var(--divider-color, #e0e0e0));
    background-image: linear-gradient(
      to right,
      transparent 0,
      transparent calc(25% - 1px),
      rgba(127, 127, 127, 0.35) calc(25% - 1px),
      rgba(127, 127, 127, 0.35) 25%
    );
    background-size: 25% 100%;
    overflow: hidden;
  }
  .bar {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 3px;
    min-width: 2px;
  }
  .heads {
    margin-top: 14px;
  }
  .heads-title {
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--secondary-text-color);
    margin-bottom: 6px;
  }
  .heads-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .head-name {
    font-size: 0.9rem;
    color: var(--primary-text-color);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .badges {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex: 0 0 auto;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .badge {
    display: inline-flex;
    width: 20px;
    height: 20px;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
  }
  .badge svg {
    width: 15px;
    height: 15px;
    fill: currentColor;
  }
  .badge.ok {
    color: var(--success-color, #2e7d32);
  }
  .badge.warn {
    color: var(--warning-color, #ffa600);
  }
  .badge.off,
  .badge.muted {
    color: var(--disabled-text-color, #9e9e9e);
  }
  .pill {
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--secondary-background-color, #eee);
    color: var(--primary-text-color);
    white-space: nowrap;
  }
  .pill.ok {
    background: var(--success-color, #2e7d32);
    color: var(--text-primary-color, #fff);
  }
  .pill.warn {
    background: var(--warning-color, #ffa600);
    color: var(--text-primary-color, #fff);
  }
  .pill.off {
    background: var(--disabled-text-color, #9e9e9e);
    color: var(--text-primary-color, #fff);
  }
  .job {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
  }
  .job-title {
    font-size: 0.8rem;
    color: var(--secondary-text-color);
  }
  .footer {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
    margin-top: 16px;
  }
  .refresh {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 16px;
    padding: 5px 12px;
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    font: inherit;
    font-size: 0.85rem;
  }
  .refresh:hover:not(:disabled) {
    background: var(--secondary-background-color, #f0f0f0);
  }
  .refresh:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .refresh svg {
    width: 16px;
    height: 16px;
    fill: currentColor;
  }
  .read-at {
    color: var(--secondary-text-color);
    font-size: 0.8rem;
  }
  .version {
    margin-left: auto;
    color: var(--secondary-text-color);
    font-size: 0.75rem;
  }
  .reload {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 12px;
    padding: 8px 12px;
    border-radius: 8px;
    background: var(--warning-color, #ffa600);
    color: var(--text-primary-color, #fff);
  }
  .reload button {
    cursor: pointer;
    border: none;
    border-radius: 6px;
    padding: 4px 12px;
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    font: inherit;
  }
`;

// Icônes inline (style mdi, 24×24, currentColor) : pas de dépendance à ha-icon,
// pour rester utilisable dans la page de démo hors Home Assistant.
export const ICON_CHECK = svg`<svg viewBox="0 0 24 24"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.42z" /></svg>`;
export const ICON_MINUS = svg`<svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14z" /></svg>`;
export const ICON_PLUS = svg`<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" /></svg>`;
export const ICON_ALERT = svg`<svg viewBox="0 0 24 24"><path d="M13 14h-2V9h2m0 9h-2v-2h2M1 21h22L12 2z" /></svg>`;
export const ICON_WRENCH = svg`<svg viewBox="0 0 24 24"><path d="M22.7 19 13.6 9.9c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z" /></svg>`;
export const ICON_WIFI = svg`<svg viewBox="0 0 24 24"><path d="M12 21 2 9c5.5-5 14.5-5 20 0zm0-3.5 3.5-4.2a5.3 5.3 0 0 0-7 0z" /></svg>`;
export const ICON_WIFI_OFF = svg`<svg viewBox="0 0 24 24"><path d="M2.3 4.3 1 5.6l2.3 2.3C2.8 8.3 2.4 8.6 2 9l10 12 3.3-4L18 19.7l1.3-1.4zM12 21ZM20.6 8.3A14 14 0 0 0 9.9 5.8l9.1 9.1 2.9-3.6c-.4-.3-.8-.7-1.3-1z" /></svg>`;
export const ICON_REFRESH = svg`<svg viewBox="0 0 24 24"><path d="M17.65 6.35A8 8 0 1 0 19.73 14h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z" /></svg>`;
export const ICON_EDIT = svg`<svg viewBox="0 0 24 24"><path d="M20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75M3 17.25V21h3.75L17.81 9.93l-3.75-3.75z" /></svg>`;
export const ICON_SAVE = svg`<svg viewBox="0 0 24 24"><path d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7zm-5 16a3 3 0 1 1 0-6 3 3 0 0 1 0 6m3-10H5V5h10z" /></svg>`;
export const ICON_TRASH = svg`<svg viewBox="0 0 24 24"><path d="M19 4h-3.5l-1-1h-5l-1 1H5v2h14zM6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6z" /></svg>`;
export const ICON_COPY = svg`<svg viewBox="0 0 24 24"><path d="M19 21H8V7h11m0-2H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2m-3-4H4a2 2 0 0 0-2 2v14h2V3h12z" /></svg>`;
export const ICON_RESTORE = svg`<svg viewBox="0 0 24 24"><path d="M13 3a9 9 0 0 0-9 9H1l4 4 4-4H6a7 7 0 1 1 7 7c-1.9 0-3.6-.8-4.9-2l-1.4 1.4A9 9 0 1 0 13 3m-1 5v5l4 2 .7-1.2-3.2-1.9V8z" /></svg>`;
export const ICON_BATTERY = svg`<svg viewBox="0 0 24 24"><path d="M16.67 4H15V2H9v2H7.33C6.6 4 6 4.6 6 5.33v15.33C6 21.4 6.6 22 7.33 22h9.33c.74 0 1.34-.6 1.34-1.33V5.33C18 4.6 17.4 4 16.67 4" /></svg>`;
export const ICON_VALVE = svg`<svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7.76A4 4 0 1 0 15 16a4 4 0 0 0-2-3.24V5a1 1 0 0 1 2 0h2a3 3 0 0 0-3-3z" /></svg>`;
export const ICON_WINDOW = svg`<svg viewBox="0 0 24 24"><path d="M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1m7 2H5v6h6zm2 0v6h6V5zm-2 8H5v6h6zm2 0v6h6v-6z" /></svg>`;
export const ICON_FLAME = svg`<svg viewBox="0 0 24 24"><path d="M17.66 11.2c-.23-.3-.51-.56-.77-.82-.67-.6-1.43-1.03-2.07-1.66C13.33 7.26 13 4.85 13.95 3c-.95.23-1.78.75-2.49 1.32-2.59 2.08-3.61 5.75-2.39 8.9.04.1.08.2.08.33 0 .22-.15.42-.35.5-.23.1-.47.04-.66-.12a.6.6 0 0 1-.14-.17c-1.13-1.43-1.31-3.48-.55-5.12C5.78 10 4.87 12.3 5 14.47c.06.5.12 1 .29 1.5.14.6.41 1.2.71 1.73 1.08 1.73 2.95 2.97 4.96 3.22 2.14.27 4.43-.12 6.07-1.6 1.83-1.66 2.47-4.32 1.53-6.6l-.13-.26c-.21-.46-.77-1.26-.77-1.26" /></svg>`;
export const ICON_THERMOMETER = svg`<svg viewBox="0 0 24 24"><path d="M15 13V5a3 3 0 0 0-6 0v8a5 5 0 1 0 6 0m-3-9a1 1 0 0 1 1 1v3h-2V5a1 1 0 0 1 1-1" /></svg>`;
export const ICON_LOCK = svg`<svg viewBox="0 0 24 24"><path d="M12 17a2 2 0 0 0 2-2 2 2 0 0 0-2-2 2 2 0 0 0-2 2 2 2 0 0 0 2 2m6-9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2h1V6a5 5 0 0 1 10 0v2zM12 3a3 3 0 0 0-3 3v2h6V6a3 3 0 0 0-3-3" /></svg>`;
