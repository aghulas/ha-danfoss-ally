/**
 * Carte `danfoss-ally-room-card` (axe D) — une pièce Danfoss Ally d'un coup d'œil.
 *
 * Lecture : température, mode et consigne de la pièce ; consignes confort / réduit ;
 * bande du programme hebdomadaire (réutilise la logique de la carte programme) ;
 * état des têtes (en ligne, batterie, vanne, fenêtre, défaut, programme / incohérence).
 *
 * Actions (administrateur) : régler la consigne ± via `climate.set_temperature` sur
 * l'entité de pièce (service DÉJÀ validé — aucun nouveau chemin d'écriture, contrat
 * §8.1), « revenir au programme » (R4), et « modifier le programme » qui déplie
 * directement l'éditeur de la carte programme en mode `embedded` (sans dupliquer
 * l'enrobage, les consignes ni les têtes). Lecture seule si l'utilisateur n'est pas
 * administrateur.
 *
 * Thème via les variables de Home Assistant, textes traduits en / fr, se dégrade
 * proprement et n'appelle que les commandes WebSocket du contrat §5.3.
 */
import { LitElement, type TemplateResult, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import {
  ICON_ALERT,
  ICON_BATTERY,
  ICON_EDIT,
  ICON_LOCK,
  ICON_MINUS,
  ICON_PLUS,
  ICON_RESTORE,
  ICON_VALVE,
  ICON_WIFI,
  ICON_WIFI_OFF,
  ICON_WINDOW,
  ICON_WRENCH,
  cardSharedStyles,
  renderBadge,
  renderCardFooter,
  renderJobBanner,
  renderReadGrid,
  renderReloadBanner,
  renderSetpoints,
} from "./card-shared";
import { errorText, modeLabel, t } from "./localize";
import {
  canAdjustSetpoint,
  isLowBattery,
  roomNeedsRestore,
  steppedSetpoint,
} from "./room";
import "./schedule-card";
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
  embedded?: boolean;
  setConfig(config: { room_id?: string }): void;
  cancelEdit?: () => void;
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
      const [schedule] = await Promise.all([
        fetchSchedule(this.hass, target, true),
        this._reloadRooms(),
      ]);
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
      if (this._schedCard?.cancelEdit) {
        this._schedCard.cancelEdit();
      } else {
        this._editing = false;
      }
      return;
    }
    const el = document.createElement("danfoss-ally-schedule-card") as EmbeddedScheduleCard;
    el.embedded = true;
    el.setConfig({ room_id: this._config?.room_id ?? "" });
    el.hass = this.hass;
    el.addEventListener("schedule-edit-close", ((
      ev: CustomEvent<{ schedule?: Schedule | null; job?: WriteJob | null }>,
    ) => {
      if (ev.detail?.schedule) {
        this._schedule = ev.detail.schedule;
      }
      if (ev.detail?.job) {
        this._job = ev.detail.job;
      }
      this._editing = false;
      this._schedCard = undefined;
    }) as EventListener);
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
    const comfort = this._schedule?.comfort ?? room?.comfort ?? null;
    const setback = this._schedule?.setback ?? room?.setback ?? null;
    return html`
      <ha-card>
        <div class="content">
          ${showReload ? renderReloadBanner(this.hass, () => this._reload()) : nothing}
          <div class="titlebar">
            <div class="room">${this._roomTitle(room)}</div>
            ${this._renderActions(room)}
          </div>
          ${readOnly ? html`<div class="hint">${t(this.hass, "read_only")}</div>` : nothing}
          ${this._error ? html`<div class="banner error" role="alert">${this._error}</div>` : nothing}
          ${room ? this._renderClimate(room) : nothing}
          ${renderSetpoints(this.hass, comfort, setback)}
          ${this._editing && this._schedCard
            ? this._schedCard
            : this._schedule
              ? renderReadGrid(this.hass, this._schedule)
              : html`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
          ${this._renderHeads(room)}
          ${renderJobBanner(this.hass, this._job)}
          ${renderCardFooter(
            this.hass,
            this._schedule,
            Boolean(this._target),
            this._refreshing,
            () => void this._refresh(),
          )}
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
        ${!this._editing
          ? html`<button
              class="btn primary"
              @click=${this._toggleEdit}
              aria-expanded="false"
            >
              ${ICON_EDIT}<span>${t(this.hass, "edit_schedule")}</span>
            </button>`
          : nothing}
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
          ${renderBadge(
            head.online ? "ok" : "off",
            head.online ? ICON_WIFI : ICON_WIFI_OFF,
            t(this.hass, head.online ? "head_online" : "head_offline"),
          )}
          ${head.battery != null
            ? renderBadge(
                low ? "warn" : "muted",
                ICON_BATTERY,
                t(this.hass, low ? "head_low_battery" : "head_battery", { value: head.battery }),
              )
            : nothing}
          ${head.valve_opening != null
            ? renderBadge(
                head.valve_opening > 0 ? "ok" : "muted",
                ICON_VALVE,
                t(this.hass, "head_valve", { value: head.valve_opening }),
              )
            : nothing}
          ${head.window_open
            ? renderBadge("warn", ICON_WINDOW, t(this.hass, "head_window_open"))
            : nothing}
          ${head.child_lock
            ? renderBadge("muted", ICON_LOCK, t(this.hass, "head_child_lock"))
            : nothing}
          ${head.inconsistent
            ? renderBadge("warn", ICON_ALERT, t(this.hass, "head_inconsistent"))
            : nothing}
          ${head.mounting
            ? renderBadge("muted", ICON_WRENCH, t(this.hass, "head_mounting"))
            : nothing}
          ${(head.faults ?? []).map((f) =>
            renderBadge("warn", ICON_ALERT, t(this.hass, "head_fault", { code: f.code })),
          )}
        </span>
      </div>
    `;
  }

  static styles = [
    cardSharedStyles,
    css`
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
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-room-card": DanfossAllyRoomCard;
  }
}
