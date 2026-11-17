/**
 * Carte `danfoss-ally-schedule-card` — lecture du programme (lot 4).
 *
 * Affiche, pour la pièce choisie : son nom, les consignes confort / réduit, la
 * grille des sept jours avec les plages de confort positionnées sur 24 h, l'état
 * des têtes (en ligne, programme actif, incohérente, en montage), un bouton
 * « actualiser » et la date de dernière lecture. Thème via les variables de Home
 * Assistant, utilisable au clavier, textes traduits en / fr (aucun texte en dur).
 *
 * Elle consomme uniquement les commandes WebSocket du contrat §5.3 et se dégrade
 * proprement si elles manquent (lot 2 non déployé) : noms de pièces vides, pas de
 * programme → message, jamais d'erreur bloquante.
 */
import { LitElement, type TemplateResult, css, html, nothing, svg } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import "./schedule-card-editor";
import { dayLabel, language, t } from "./localize";
import {
  DAY_KEYS,
  type Bar,
  dayBars,
  formatReadAt,
  isSetbackOnly,
} from "./schedule";
import type {
  DayKey,
  HassLike,
  HeadState,
  Info,
  Room,
  Schedule,
  ScheduleCardConfig,
  Target,
} from "./types";
import { CARD_VERSION, needsReload } from "./version";
import { fetchInfo, fetchRooms, fetchSchedule, pickRoom } from "./ws";

@customElement("danfoss-ally-schedule-card")
export class DanfossAllyScheduleCard extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;

  @state() private _config?: ScheduleCardConfig;
  @state() private _rooms: Room[] = [];
  @state() private _info: Info | null = null;
  @state() private _schedule: Schedule | null = null;
  @state() private _loaded = false;
  @state() private _refreshing = false;

  public static getConfigElement(): HTMLElement {
    return document.createElement("danfoss-ally-schedule-card-editor");
  }

  public static getStubConfig(): ScheduleCardConfig {
    return { room_id: "" };
  }

  public setConfig(config: ScheduleCardConfig): void {
    if (!config) {
      throw new Error("Configuration invalide");
    }
    this._config = config;
  }

  public getCardSize(): number {
    return 6;
  }

  protected updated(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }

  private get _target(): Target | undefined {
    const id = this._config?.room_id;
    return id ? { type: "room", id } : undefined;
  }

  private async _load(): Promise<void> {
    if (!this.hass) {
      return;
    }
    const target = this._target;
    const [info, rooms, schedule] = await Promise.all([
      fetchInfo(this.hass),
      fetchRooms(this.hass),
      target ? fetchSchedule(this.hass, target) : Promise.resolve(null),
    ]);
    this._info = info;
    this._rooms = rooms;
    this._schedule = schedule;
  }

  private async _refresh(): Promise<void> {
    const target = this._target;
    if (!this.hass || !target || this._refreshing) {
      return;
    }
    this._refreshing = true;
    try {
      const schedule = await fetchSchedule(this.hass, target, true);
      if (schedule) {
        this._schedule = schedule;
      }
    } finally {
      this._refreshing = false;
    }
  }

  private _reload(): void {
    globalThis.location?.reload();
  }

  protected render(): TemplateResult {
    const room = pickRoom(this._rooms, this._config?.room_id);
    const showReload = needsReload(CARD_VERSION, this._info?.version);
    const readOnly = this._info !== null && !this._info.is_admin;

    return html`
      <ha-card>
        <div class="content">
          ${showReload ? this._renderReloadBanner() : nothing}
          <div class="room">${this._roomTitle(room)}</div>
          ${readOnly ? html`<div class="hint">${t(this.hass, "read_only")}</div>` : nothing}
          ${this._renderBody(room)}
        </div>
      </ha-card>
    `;
  }

  private _renderBody(room: Room | undefined): TemplateResult {
    if (this._rooms.length === 0 && !this._config?.room_id) {
      return html`<div class="hint">${t(this.hass, "rooms_unavailable")}</div>`;
    }
    const schedule = this._schedule;
    const comfort = schedule?.comfort ?? room?.comfort ?? null;
    const setback = schedule?.setback ?? room?.setback ?? null;

    return html`
      ${this._renderSetpoints(comfort, setback)}
      ${schedule
        ? this._renderGrid(schedule)
        : html`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
      ${this._renderHeads(room)}
      ${this._renderFooter(schedule)}
    `;
  }

  private _roomTitle(room: Room | undefined): string {
    if (room) {
      return room.name;
    }
    if (this._schedule?.name) {
      return this._schedule.name;
    }
    if (this._config?.room_id) {
      return t(this.hass, "unknown_room", { id: this._config.room_id });
    }
    return t(this.hass, "no_room");
  }

  private _renderSetpoints(comfort: number | null, setback: number | null): TemplateResult {
    const fmt = (v: number | null): string =>
      v === null ? "—" : t(this.hass, "degree", { value: v });
    return html`
      <div class="setpoints">
        <span class="chip comfort">
          <span class="swatch comfort"></span>${t(this.hass, "comfort")} ${fmt(comfort)}
        </span>
        <span class="chip setback">
          <span class="swatch setback"></span>${t(this.hass, "setback")} ${fmt(setback)}
        </span>
      </div>
    `;
  }

  private _renderGrid(schedule: Schedule): TemplateResult {
    return html`
      <div class="grid">
        <div class="scale" aria-hidden="true">
          <span>0 h</span><span>6 h</span><span>12 h</span><span>18 h</span><span>24 h</span>
        </div>
        ${DAY_KEYS.map((day) => this._renderDay(day, schedule.days[day] ?? []))}
      </div>
    `;
  }

  private _renderDay(day: DayKey, ranges: Schedule["days"][DayKey]): TemplateResult {
    const bars = dayBars(ranges);
    const label = this._dayAria(day, bars, isSetbackOnly(ranges));
    return html`
      <div class="day">
        <span class="day-label">${dayLabel(this.hass, day)}</span>
        <div class="track" role="img" aria-label=${label}>
          ${bars.map(
            (bar) => html`
              <div
                class="bar"
                style="left:${bar.leftPct}%;width:${bar.widthPct}%"
                title=${t(this.hass, "range_label", { start: bar.start, end: bar.end })}
              ></div>
            `,
          )}
        </div>
      </div>
    `;
  }

  private _dayAria(day: DayKey, bars: Bar[], setbackOnly: boolean): string {
    const name = dayLabel(this.hass, day);
    if (setbackOnly) {
      return `${name} — ${t(this.hass, "setback_all_day")}`;
    }
    const parts = bars.map((bar) =>
      t(this.hass, "range_label", { start: bar.start, end: bar.end }),
    );
    return `${name} — ${parts.join(", ")}`;
  }

  private _renderHeads(room: Room | undefined): TemplateResult {
    const heads = room?.heads ?? [];
    return html`
      <div class="heads">
        <div class="heads-title">${t(this.hass, "heads_heading")}</div>
        ${heads.length === 0
          ? html`<div class="hint">${t(this.hass, "heads_none")}</div>`
          : html`<div class="heads-list">
              ${heads.map((head) => this._renderHead(head))}
            </div>`}
      </div>
    `;
  }

  private _renderHead(head: HeadState): TemplateResult {
    return html`
      <div class="head">
        <span class="head-name">${head.name}</span>
        <span class="badges">
          ${this._badge(
            head.online ? "ok" : "off",
            head.online ? ICON_WIFI : ICON_WIFI_OFF,
            t(this.hass, head.online ? "head_online" : "head_offline"),
          )}
          ${head.schedule_active !== null
            ? this._badge(
                head.schedule_active ? "ok" : "muted",
                head.schedule_active ? ICON_CHECK : ICON_MINUS,
                t(this.hass, head.schedule_active ? "head_schedule_on" : "head_schedule_off"),
              )
            : nothing}
          ${head.inconsistent
            ? this._badge("warn", ICON_ALERT, t(this.hass, "head_inconsistent"))
            : nothing}
          ${head.mounting
            ? this._badge("muted", ICON_WRENCH, t(this.hass, "head_mounting"))
            : nothing}
        </span>
      </div>
    `;
  }

  private _badge(kind: string, icon: TemplateResult, label: string): TemplateResult {
    return html`
      <span class="badge ${kind}" title=${label} role="img" aria-label=${label}>${icon}</span>
    `;
  }

  private _renderFooter(schedule: Schedule | null): TemplateResult {
    const when = formatReadAt(schedule?.read_at, language(this.hass));
    const lastRead = when
      ? t(this.hass, "last_read", { when })
      : t(this.hass, "never_read");
    const canRefresh = Boolean(this.hass && this._target);
    return html`
      <div class="footer">
        <button
          class="refresh"
          @click=${this._refresh}
          ?disabled=${!canRefresh || this._refreshing}
          aria-label=${t(this.hass, "refresh")}
        >
          ${ICON_REFRESH}<span>${t(this.hass, "refresh")}</span>
        </button>
        <span class="read-at">${lastRead}</span>
        <span class="version">${t(this.hass, "version", { version: CARD_VERSION })}</span>
      </div>
    `;
  }

  private _renderReloadBanner(): TemplateResult {
    return html`
      <div class="reload">
        <span>${t(this.hass, "reload_available")}</span>
        <button @click=${this._reload}>${t(this.hass, "reload")}</button>
      </div>
    `;
  }

  static styles = css`
    :host {
      display: block;
    }
    .content {
      padding: 0 16px 16px;
    }
    .room {
      font-size: 1.4rem;
      font-weight: 500;
      color: var(--primary-text-color);
      padding-top: 16px;
    }
    .hint {
      margin-top: 8px;
      color: var(--secondary-text-color);
      font-size: 0.9rem;
    }
    .setpoints {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 12px 0;
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
    .refresh:hover {
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
}

// Icônes inline (style mdi, 24×24, currentColor) : pas de dépendance à ha-icon,
// pour rester utilisable dans la page de démo hors Home Assistant.
const ICON_CHECK = svg`<svg viewBox="0 0 24 24"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.42z" /></svg>`;
const ICON_MINUS = svg`<svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14z" /></svg>`;
const ICON_ALERT = svg`<svg viewBox="0 0 24 24"><path d="M13 14h-2V9h2m0 9h-2v-2h2M1 21h22L12 2z" /></svg>`;
const ICON_WRENCH = svg`<svg viewBox="0 0 24 24"><path d="M22.7 19 13.6 9.9c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z" /></svg>`;
const ICON_WIFI = svg`<svg viewBox="0 0 24 24"><path d="M12 21 2 9c5.5-5 14.5-5 20 0zm0-3.5 3.5-4.2a5.3 5.3 0 0 0-7 0z" /></svg>`;
const ICON_WIFI_OFF = svg`<svg viewBox="0 0 24 24"><path d="M2.3 4.3 1 5.6l2.3 2.3C2.8 8.3 2.4 8.6 2 9l10 12 3.3-4L18 19.7l1.3-1.4zM12 21ZM20.6 8.3A14 14 0 0 0 9.9 5.8l9.1 9.1 2.9-3.6c-.4-.3-.8-.7-1.3-1z" /></svg>`;
const ICON_REFRESH = svg`<svg viewBox="0 0 24 24"><path d="M17.65 6.35A8 8 0 1 0 19.73 14h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z" /></svg>`;

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-schedule-card": DanfossAllyScheduleCard;
  }
}
