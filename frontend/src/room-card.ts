/**
 * Carte `danfoss-ally-room-card` (axe D) — une pièce Danfoss Ally d'un coup d'œil.
 *
 * Lecture : température, mode et consigne de la pièce ; consignes confort / réduit ;
 * bande du programme hebdomadaire (réutilise la logique de la carte programme) ;
 * état des têtes (en ligne, batterie, vanne, fenêtre, défaut, programme / incohérence).
 *
 * Actions (administrateur) : régler la consigne ± via `climate.set_temperature` sur
 * l'entité de pièce (service DÉJÀ validé — aucun nouveau chemin d'écriture, contrat
 * §8.1), « revenir au programme » (R4), et « modifier le programme » qui déplie la
 * carte programme existante. Lecture seule si l'utilisateur n'est pas administrateur.
 *
 * Thème via les variables de Home Assistant, textes traduits en / fr, se dégrade
 * proprement et n'appelle que les commandes WebSocket du contrat §5.3.
 */
import { LitElement, type TemplateResult, css, html, nothing, svg } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import "./schedule-card";
import { dayLabel, errorText, language, modeLabel, t } from "./localize";
import {
  canAdjustSetpoint,
  isLowBattery,
  roomNeedsRestore,
  steppedSetpoint,
} from "./room";
import { DAY_KEYS, type Bar, dayBars, formatReadAt, isSetbackOnly } from "./schedule";
import type {
  HassLike,
  HeadState,
  Info,
  Room,
  RoomCardConfig,
  Schedule,
  Target,
  WriteJob,
} from "./types";
import { CARD_VERSION, needsReload } from "./version";
import {
  ScheduleCommandError,
  fetchInfo,
  fetchRooms,
  fetchSchedule,
  pickRoom,
  restoreSchedule,
  subscribeJobs,
} from "./ws";

type EmbeddedScheduleCard = HTMLElement & {
  hass?: HassLike;
  setConfig(config: { room_id?: string }): void;
};

@customElement("danfoss-ally-room-card")
export class DanfossAllyRoomCard extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;

  @state() private _config?: RoomCardConfig;
  @state() private _rooms: Room[] = [];
  @state() private _info: Info | null = null;
  @state() private _schedule: Schedule | null = null;
  @state() private _loaded = false;
  @state() private _refreshing = false;
  @state() private _busy = false;
  @state() private _error: string | null = null;
  @state() private _editing = false;
  @state() private _job: WriteJob | null = null;

  private _unsubscribe: (() => void) | null = null;
  private _schedCard?: EmbeddedScheduleCard;

  public static getConfigElement(): HTMLElement {
    return document.createElement("danfoss-ally-room-card-editor");
  }

  public static getStubConfig(): RoomCardConfig {
    return { room_id: "" };
  }

  public setConfig(config: RoomCardConfig): void {
    if (!config) {
      throw new Error("Configuration invalide");
    }
    if (config.room_id !== this._config?.room_id) {
      this._editing = false;
      this._schedCard = undefined;
    }
    this._config = config;
  }

  public getCardSize(): number {
    return this._editing ? 12 : 6;
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    this._unsubscribe?.();
    this._unsubscribe = null;
  }

  protected updated(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass) {
      if (!this._loaded) {
        this._loaded = true;
        void this._load();
      }
      if (this._schedCard) {
        this._schedCard.hass = this.hass;
      }
    }
  }

  private get _room(): Room | undefined {
    return pickRoom(this._rooms, this._config?.room_id);
  }

  private get _target(): Target | undefined {
    const id = this._config?.room_id;
    return id ? { type: "room", id } : undefined;
  }

  private get _isAdmin(): boolean {
    return this._info !== null && this._info.is_admin;
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
    if (!this._unsubscribe) {
      this._unsubscribe = await subscribeJobs(this.hass, (job) => this._onJob(job));
    }
  }

  private _onJob(job: WriteJob): void {
    if (job.target?.id === this._config?.room_id) {
      this._job = job;
    }
  }

  private async _reloadRooms(): Promise<void> {
    if (this.hass) {
      this._rooms = await fetchRooms(this.hass);
    }
  }

  private async _refresh(): Promise<void> {
    const target = this._target;
    if (!this.hass || !target || this._refreshing) {
      return;
    }
    this._refreshing = true;
    try {
      const [schedule] = await Promise.all([fetchSchedule(this.hass, target, true), this._reloadRooms()]);
      if (schedule) {
        this._schedule = schedule;
      }
    } finally {
      this._refreshing = false;
    }
  }

  private async _adjust(direction: 1 | -1): Promise<void> {
    const room = this._room;
    if (!this.hass?.callService || !room || !canAdjustSetpoint(room) || this._busy) {
      return;
    }
    const next = steppedSetpoint(room.setpoint as number, direction);
    this._busy = true;
    this._error = null;
    try {
      await this.hass.callService("climate", "set_temperature", {
        entity_id: room.climate_entity_id,
        temperature: next,
      });
      // Optimiste, puis relecture (le cloud applique en quelques secondes).
      this._rooms = this._rooms.map((r) => (r.id === room.id ? { ...r, setpoint: next } : r));
      await this._reloadRooms();
    } catch (err) {
      const code = err instanceof ScheduleCommandError ? err.code : "unknown";
      this._error = errorText(this.hass, code);
    } finally {
      this._busy = false;
    }
  }

  private async _restore(): Promise<void> {
    const target = this._target;
    if (!this.hass || !target || this._busy) {
      return;
    }
    this._busy = true;
    this._error = null;
    try {
      this._job = await restoreSchedule(this.hass, target);
    } catch (err) {
      const code = err instanceof ScheduleCommandError ? err.code : "unknown";
      this._error = errorText(this.hass, code);
    } finally {
      this._busy = false;
    }
  }

  private _toggleEdit(): void {
    if (this._editing) {
      this._editing = false;
      return;
    }
    const el = document.createElement("danfoss-ally-schedule-card") as EmbeddedScheduleCard;
    el.setConfig({ room_id: this._config?.room_id ?? "" });
    el.hass = this.hass;
    this._schedCard = el;
    this._editing = true;
  }

  private _reload(): void {
    globalThis.location?.reload();
  }

  // --- Rendu ---

  protected render(): TemplateResult {
    const room = this._room;
    const showReload = needsReload(CARD_VERSION, this._info?.version);
    const readOnly = this._info !== null && !this._info.is_admin;
    return html`
      <ha-card>
        <div class="content">
          ${showReload ? this._renderReloadBanner() : nothing}
          <div class="titlebar">
            <div class="room">${this._roomTitle(room)}</div>
            ${this._renderActions(room)}
          </div>
          ${readOnly ? html`<div class="hint">${t(this.hass, "read_only")}</div>` : nothing}
          ${this._error ? html`<div class="banner error" role="alert">${this._error}</div>` : nothing}
          ${room ? this._renderClimate(room) : nothing}
          ${this._renderSetpoints(room)}
          ${this._editing && this._schedCard
            ? this._schedCard
            : this._schedule
              ? this._renderGrid(this._schedule)
              : html`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
          ${this._renderHeads(room)}
          ${this._renderJob()}
          ${this._renderFooter(this._schedule)}
        </div>
      </ha-card>
    `;
  }

  private _roomTitle(room: Room | undefined): string {
    if (room) {
      return room.name;
    }
    if (this._config?.room_id) {
      return t(this.hass, "unknown_room", { id: this._config.room_id });
    }
    return t(this.hass, "no_room");
  }

  private _renderActions(room: Room | undefined): TemplateResult | typeof nothing {
    if (!this._isAdmin || !room) {
      return nothing;
    }
    return html`
      <div class="actions">
        ${roomNeedsRestore(room)
          ? html`<button
              class="btn ghost"
              @click=${this._restore}
              ?disabled=${this._busy}
              title=${t(this.hass, "restore_hint")}
            >
              ${ICON_RESTORE}<span>${t(this.hass, "restore_schedule")}</span>
            </button>`
          : nothing}
        <button
          class="btn primary"
          @click=${this._toggleEdit}
          aria-expanded=${this._editing ? "true" : "false"}
        >
          ${ICON_EDIT}<span>${this._editing ? t(this.hass, "cancel") : t(this.hass, "edit_schedule")}</span>
        </button>
      </div>
    `;
  }

  private _renderClimate(room: Room): TemplateResult {
    const deg = (v: number | null | undefined): string =>
      v === null || v === undefined ? "—" : t(this.hass, "degree", { value: v });
    const canAdjust = this._isAdmin && Boolean(this.hass?.callService) && canAdjustSetpoint(room);
    return html`
      <div class="climate">
        <div class="metric">
          <span class="big ${room.heating ? "heating" : ""}">${deg(room.temperature)}</span>
          <span class="metric-label">${modeLabel(this.hass, room.mode)}</span>
        </div>
        <div class="setpoint">
          ${canAdjust
            ? html`<button
                class="step"
                @click=${() => this._adjust(-1)}
                ?disabled=${this._busy}
                aria-label=${t(this.hass, "cooler")}
                title=${t(this.hass, "cooler")}
              >
                ${ICON_MINUS}
              </button>`
            : nothing}
          <span class="target">${deg(room.setpoint)}</span>
          ${canAdjust
            ? html`<button
                class="step"
                @click=${() => this._adjust(1)}
                ?disabled=${this._busy}
                aria-label=${t(this.hass, "warmer")}
                title=${t(this.hass, "warmer")}
              >
                ${ICON_PLUS}
              </button>`
            : nothing}
        </div>
      </div>
    `;
  }

  private _renderSetpoints(room: Room | undefined): TemplateResult {
    const comfort = this._schedule?.comfort ?? room?.comfort ?? null;
    const setback = this._schedule?.setback ?? room?.setback ?? null;
    const fmt = (v: number | null): string =>
      v === null ? "—" : t(this.hass, "degree", { value: v });
    return html`
      <div class="setpoints">
        <span class="chip">
          <span class="swatch comfort"></span>${t(this.hass, "comfort")} ${fmt(comfort)}
        </span>
        <span class="chip">
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

  private _renderDay(day: (typeof DAY_KEYS)[number], ranges: Schedule["days"][keyof Schedule["days"]]): TemplateResult {
    const bars = dayBars(ranges);
    const label = isSetbackOnly(ranges)
      ? `${dayLabel(this.hass, day)} — ${t(this.hass, "setback_all_day")}`
      : `${dayLabel(this.hass, day)} — ${bars
          .map((b) => t(this.hass, "range_label", { start: b.start, end: b.end }))
          .join(", ")}`;
    return html`
      <div class="day">
        <span class="day-label">${dayLabel(this.hass, day)}</span>
        <div class="track" role="img" aria-label=${label}>
          ${bars.map(
            (bar: Bar) => html`
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

  private _renderHeads(room: Room | undefined): TemplateResult {
    const heads = room?.heads ?? [];
    return html`
      <div class="heads">
        <div class="heads-title">${t(this.hass, "heads_heading")}</div>
        ${heads.length === 0
          ? html`<div class="hint">${t(this.hass, "heads_none")}</div>`
          : html`<div class="heads-list">${heads.map((head) => this._renderHead(head))}</div>`}
      </div>
    `;
  }

  private _renderHead(head: HeadState): TemplateResult {
    const low = isLowBattery(head);
    return html`
      <div class="head">
        <span class="head-name">${head.name}</span>
        <span class="badges">
          ${this._badge(
            head.online ? "ok" : "off",
            head.online ? ICON_WIFI : ICON_WIFI_OFF,
            t(this.hass, head.online ? "head_online" : "head_offline"),
          )}
          ${head.battery != null
            ? this._badge(
                low ? "warn" : "muted",
                ICON_BATTERY,
                t(this.hass, low ? "head_low_battery" : "head_battery", { value: head.battery }),
              )
            : nothing}
          ${head.valve_opening != null
            ? this._badge(
                head.valve_opening > 0 ? "ok" : "muted",
                ICON_VALVE,
                t(this.hass, "head_valve", { value: head.valve_opening }),
              )
            : nothing}
          ${head.window_open
            ? this._badge("warn", ICON_WINDOW, t(this.hass, "head_window_open"))
            : nothing}
          ${head.child_lock
            ? this._badge("muted", ICON_LOCK, t(this.hass, "head_child_lock"))
            : nothing}
          ${head.inconsistent
            ? this._badge("warn", ICON_ALERT, t(this.hass, "head_inconsistent"))
            : nothing}
          ${head.mounting ? this._badge("muted", ICON_WRENCH, t(this.hass, "head_mounting")) : nothing}
          ${(head.faults ?? []).map((f) =>
            this._badge("warn", ICON_ALERT, t(this.hass, "head_fault", { code: f.code })),
          )}
        </span>
      </div>
    `;
  }

  private _badge(kind: string, icon: TemplateResult, label: string): TemplateResult {
    return html`<span class="badge ${kind}" title=${label} role="img" aria-label=${label}>${icon}</span>`;
  }

  private _renderJob(): TemplateResult | typeof nothing {
    const job = this._job;
    if (!job) {
      return nothing;
    }
    const key = `job_status_${job.status}` as Parameters<typeof t>[1];
    const kind =
      job.status === "applied"
        ? "ok"
        : job.status === "partial"
          ? "warn"
          : job.status === "failed"
            ? "off"
            : "muted";
    return html`
      <div class="job">
        <span class="job-title">${t(this.hass, "job_heading")}</span>
        <span class="pill ${kind}">${t(this.hass, key)}</span>
      </div>
    `;
  }

  private _renderFooter(schedule: Schedule | null): TemplateResult {
    const when = formatReadAt(schedule?.read_at, language(this.hass));
    const lastRead = when ? t(this.hass, "last_read", { when }) : t(this.hass, "never_read");
    return html`
      <div class="footer">
        <button
          class="refresh"
          @click=${this._refresh}
          ?disabled=${!this._target || this._refreshing}
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
    .btn.ghost {
      background: transparent;
    }
    .climate {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin: 12px 0 4px;
    }
    .metric {
      display: flex;
      flex-direction: column;
    }
    .big {
      font-size: 2rem;
      font-weight: 300;
      line-height: 1.1;
      color: var(--primary-text-color);
    }
    .big.heating {
      color: var(--danfoss-comfort-color, var(--primary-color, #ff8a33));
    }
    .metric-label {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
    .setpoint {
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }
    .target {
      font-size: 1.4rem;
      font-variant-numeric: tabular-nums;
      min-width: 3.5rem;
      text-align: center;
      color: var(--primary-text-color);
    }
    .step {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      cursor: pointer;
    }
    .step svg {
      width: 20px;
      height: 20px;
      fill: currentColor;
    }
    .step:hover:not(:disabled) {
      background: var(--secondary-background-color, #f0f0f0);
    }
    .step:disabled {
      opacity: 0.5;
      cursor: default;
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
    .refresh svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }
    .refresh:disabled {
      opacity: 0.6;
      cursor: default;
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

// Icônes inline (style mdi), pas de dépendance à ha-icon.
const ICON_MINUS = svg`<svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14z" /></svg>`;
const ICON_PLUS = svg`<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" /></svg>`;
const ICON_ALERT = svg`<svg viewBox="0 0 24 24"><path d="M13 14h-2V9h2m0 9h-2v-2h2M1 21h22L12 2z" /></svg>`;
const ICON_WRENCH = svg`<svg viewBox="0 0 24 24"><path d="M22.7 19 13.6 9.9c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z" /></svg>`;
const ICON_WIFI = svg`<svg viewBox="0 0 24 24"><path d="M12 21 2 9c5.5-5 14.5-5 20 0zm0-3.5 3.5-4.2a5.3 5.3 0 0 0-7 0z" /></svg>`;
const ICON_WIFI_OFF = svg`<svg viewBox="0 0 24 24"><path d="M2.3 4.3 1 5.6l2.3 2.3C2.8 8.3 2.4 8.6 2 9l10 12 3.3-4L18 19.7l1.3-1.4zM20.6 8.3A14 14 0 0 0 9.9 5.8l9.1 9.1 2.9-3.6c-.4-.3-.8-.7-1.3-1z" /></svg>`;
const ICON_REFRESH = svg`<svg viewBox="0 0 24 24"><path d="M17.65 6.35A8 8 0 1 0 19.73 14h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z" /></svg>`;
const ICON_EDIT = svg`<svg viewBox="0 0 24 24"><path d="M20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75M3 17.25V21h3.75L17.81 9.93l-3.75-3.75z" /></svg>`;
const ICON_RESTORE = svg`<svg viewBox="0 0 24 24"><path d="M13 3a9 9 0 0 0-9 9H1l4 4 4-4H6a7 7 0 1 1 7 7c-1.9 0-3.6-.8-4.9-2l-1.4 1.4A9 9 0 1 0 13 3m-1 5v5l4 2 .7-1.2-3.2-1.9V8z" /></svg>`;
const ICON_BATTERY = svg`<svg viewBox="0 0 24 24"><path d="M16.67 4H15V2H9v2H7.33C6.6 4 6 4.6 6 5.33v15.33C6 21.4 6.6 22 7.33 22h9.33c.74 0 1.34-.6 1.34-1.33V5.33C18 4.6 17.4 4 16.67 4" /></svg>`;
const ICON_VALVE = svg`<svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7.76A4 4 0 1 0 15 16a4 4 0 0 0-2-3.24V5a1 1 0 0 1 2 0h2a3 3 0 0 0-3-3z" /></svg>`;
const ICON_WINDOW = svg`<svg viewBox="0 0 24 24"><path d="M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1m7 2H5v6h6zm2 0v6h6V5zm-2 8H5v6h6zm2 0v6h6v-6z" /></svg>`;
const ICON_LOCK = svg`<svg viewBox="0 0 24 24"><path d="M12 17a2 2 0 0 0 2-2 2 2 0 0 0-2-2 2 2 0 0 0-2 2 2 2 0 0 0 2 2m6-9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2h1V6a5 5 0 0 1 10 0v2zM12 3a3 3 0 0 0-3 3v2h6V6a3 3 0 0 0-3-3" /></svg>`;

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-room-card": DanfossAllyRoomCard;
  }
}
