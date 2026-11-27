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
 * Par zone (`area_id`, contrat §8.3) : la carte montre aussi chaque `climate` de la
 * zone, quelle que soit son intégration (p. ex. une tête Danfoss appairée à
 * Zigbee2MQTT), avec ce que les autres entités de son appareil apportent. Si la zone
 * contient une pièce Danfoss Ally, cette pièce garde tout ce qui précède. Seule
 * écriture ajoutée : `climate.set_temperature` sur un climate HORS Ally,
 * administrateur seulement, dans ses bornes et à son pas.
 *
 * Thème via les variables de Home Assistant, textes traduits en / fr, se dégrade
 * proprement et n'appelle que les commandes WebSocket du contrat §5.3.
 */
import { LitElement, type TemplateResult, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import {
  type ClimateView,
  allyRoomsInArea,
  canAdjustClimate,
  climateView,
  climatesInArea,
  roomSensors,
  steppedClimateTarget,
} from "./area";
import {
  ICON_ALERT,
  ICON_BATTERY,
  ICON_EDIT,
  ICON_FLAME,
  ICON_LOCK,
  ICON_MINUS,
  ICON_PLUS,
  ICON_RESTORE,
  ICON_THERMOMETER,
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
import { actionLabel, errorText, modeLabel, t } from "./localize";
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
  /**
   * Aucune lecture n'a encore abouti pour la pièce configurée : la carte dit qu'elle
   * charge, au lieu d'annoncer une pièce inconnue, sans programme et sans tête.
   */
  @state() private _pending = true;
  @state() private _refreshing = false;
  @state() private _busy = false;
  @state() private _error: string | null = null;
  @state() private _editing = false;
  @state() private _job: WriteJob | null = null;
  /** Climate hors Ally en cours d'écriture (un seul envoi à la fois par carte). */
  @state() private _busyClimate: string | null = null;
  /** Pièce dont `_schedule` est le programme (la pièce d'une zone se résout après `rooms`). */
  private _scheduleRoomId: string | undefined;
  private _loading = false;

  private _unsubscribe: (() => void) | null = null;
  private _subscribing = false;
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
    const roomChanged =
      config.room_id !== this._config?.room_id || config.area_id !== this._config?.area_id;
    if (roomChanged) {
      this._editing = false;
      this._schedCard = undefined;
    }
    this._config = config;
    if (roomChanged && this._loaded) {
      // Rien de l'ancienne pièce ne doit rester affiché sous le nom de la nouvelle.
      this._schedule = null;
      this._job = null;
      this._error = null;
      this._pending = true;
      void this._load();
    }
  }

  public getCardSize(): number {
    return this._editing ? 12 : 6;
  }

  public connectedCallback(): void {
    super.connectedCallback();
    // Home Assistant détache puis rattache les cartes (changement de colonnes,
    // mode édition) : sans cela le suivi des lots resterait coupé après coup.
    if (this._loaded) {
      void this._subscribe();
    }
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
      // Zone : la pièce Ally peut changer avec les registres (appareil déplacé).
      if (
        this._loaded &&
        !this._loading &&
        this._config?.area_id &&
        this._roomId !== this._scheduleRoomId
      ) {
        void this._loadSchedule();
      }
    }
  }

  /** Clé de la configuration : une réponse lue pour une autre clé est jetée. */
  private get _configKey(): string {
    return `${this._config?.room_id ?? ""}|${this._config?.area_id ?? ""}`;
  }

  /**
   * Pièce Ally de la carte : `room_id` s'il est donné, sinon la première pièce dont
   * le thermostat de pièce est dans la zone `area_id`.
   */
  private get _roomId(): string | undefined {
    if (this._config?.room_id) {
      return this._config.room_id;
    }
    const area = this._config?.area_id;
    if (!area || !this.hass) {
      return undefined;
    }
    return allyRoomsInArea(this.hass, this._rooms, area)[0]?.id;
  }

  private get _room(): Room | undefined {
    return pickRoom(this._rooms, this._roomId);
  }

  private get _target(): Target | undefined {
    const id = this._roomId;
    return id ? { type: "room", id } : undefined;
  }

  private get _isAdmin(): boolean {
    return this._info !== null && this._info.is_admin;
  }

  /**
   * Droit d'écrire un climate hors Ally : seulement si la configuration de la carte
   * l'active (`allow_foreign_writes`, désactivé par défaut), puis celui que donne
   * `info` (même règle que la carte), ou à défaut l'utilisateur du frontend. Jamais
   * vrai sans preuve.
   */
  private get _canWriteForeign(): boolean {
    if (this._config?.allow_foreign_writes !== true) {
      return false;
    }
    if (this._info !== null) {
      return this._info.is_admin;
    }
    return this.hass?.user?.is_admin === true;
  }

  private async _load(): Promise<void> {
    if (!this.hass) {
      return;
    }
    const key = this._configKey;
    const target = this._config?.room_id ? this._target : undefined;
    this._loading = true;
    try {
      const [info, rooms, schedule] = await Promise.all([
        fetchInfo(this.hass),
        fetchRooms(this.hass),
        target ? fetchSchedule(this.hass, target) : Promise.resolve(null),
      ]);
      if (key !== this._configKey) {
        // La pièce a changé pendant la lecture : cette réponse n'est plus la sienne.
        return;
      }
      this._info = info;
      this._rooms = rooms;
      this._pending = false;
      this._schedule = schedule;
      this._scheduleRoomId = target?.id;
      if (!target && this._target) {
        // Zone : la pièce n'est connue qu'après `rooms`.
        await this._loadSchedule();
      }
    } finally {
      this._loading = false;
    }
    await this._subscribe();
  }

  /** (Re)lit le programme de la pièce courante (zone dont la pièce vient d'être résolue). */
  private async _loadSchedule(): Promise<void> {
    const target = this._target;
    const key = this._configKey;
    this._scheduleRoomId = target?.id;
    if (!this.hass || !target) {
      this._schedule = null;
      return;
    }
    const schedule = await fetchSchedule(this.hass, target);
    if (key === this._configKey && target.id === this._roomId) {
      this._schedule = schedule;
    }
  }

  private async _subscribe(): Promise<void> {
    if (!this.hass || this._unsubscribe || this._subscribing) {
      return;
    }
    this._subscribing = true;
    try {
      this._unsubscribe = await subscribeJobs(this.hass, (job) => this._onJob(job));
    } finally {
      this._subscribing = false;
    }
  }

  private _onJob(job: WriteJob): void {
    const id = this._roomId;
    if (id && job.target?.id === id) {
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
      if (schedule && target.id === this._roomId) {
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

  /**
   * ± sur un climate HORS Ally (zone) : `climate.set_temperature`, administrateur,
   * au pas du climate et dans ses bornes. Aucun état optimiste : Home Assistant
   * pousse le nouvel état du climate.
   */
  private async _adjustClimate(entityId: string, direction: 1 | -1): Promise<void> {
    if (!this.hass?.callService || !this._canWriteForeign || this._busyClimate) {
      return;
    }
    const view = climateView(this.hass, entityId);
    const next = view ? steppedClimateTarget(view, direction) : null;
    if (!view || next === null) {
      return;
    }
    this._busyClimate = entityId;
    this._error = null;
    try {
      await this.hass.callService("climate", "set_temperature", {
        entity_id: entityId,
        temperature: next,
      });
    } catch {
      this._error = t(this.hass, "climate_write_failed", { name: view.name });
    } finally {
      this._busyClimate = null;
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
    el.setConfig({ room_id: this._roomId ?? "" });
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
    const areaMode = Boolean(this._config?.area_id);
    // Première lecture en cours et pièce pas encore connue : ni « inconnue », ni corps vide.
    const loading = this._pending && !areaMode && !room && Boolean(this._config?.room_id);
    return html`
      <ha-card>
        <div class="content">
          ${showReload ? renderReloadBanner(this.hass, () => this._reload()) : nothing}
          <div class="titlebar">
            <div class="room">${loading ? t(this.hass, "loading") : this._title(room)}</div>
            ${this._renderActions(room)}
          </div>
          ${areaMode ? this._renderRoomSensors() : nothing}
          ${areaMode && room
            ? html`<div class="hint">${t(this.hass, "area_ally_room", { name: room.name })}</div>`
            : nothing}
          ${readOnly ? html`<div class="hint">${t(this.hass, "read_only")}</div>` : nothing}
          ${this._error ? html`<div class="banner error" role="alert">${this._error}</div>` : nothing}
          ${loading
            ? nothing
            : room || !areaMode
              ? this._renderAllyBody(room, comfort, setback)
              : nothing}
          ${areaMode ? this._renderAreaClimates(room) : nothing}
          ${room || !areaMode
            ? renderCardFooter(
                this.hass,
                this._schedule,
                Boolean(this._target),
                this._refreshing,
                () => void this._refresh(),
              )
            : html`<div class="footer">
                <span class="version">${t(this.hass, "version", { version: CARD_VERSION })}</span>
              </div>`}
        </div>
      </ha-card>
    `;
  }

  /** Pièce Ally : son climat, ses consignes, son programme, ses têtes, son lot (§8.1). */
  private _renderAllyBody(
    room: Room | undefined,
    comfort: number | null,
    setback: number | null,
  ): TemplateResult {
    return html`
      ${room ? this._renderClimate(room) : nothing}
      ${renderSetpoints(this.hass, comfort, setback)}
      ${this._editing && this._schedCard
        ? this._schedCard
        : this._schedule
          ? renderReadGrid(this.hass, this._schedule)
          : html`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
      ${this._renderHeads(room)}
      ${renderJobBanner(this.hass, this._job)}
    `;
  }

  private _title(room: Room | undefined): string {
    const areaId = this._config?.area_id;
    if (areaId) {
      const area = this.hass?.areas?.[areaId];
      return area ? area.name : t(this.hass, "unknown_area", { id: areaId });
    }
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

  /**
   * Capteurs de pièce de la zone (hors appareils de climates) : un seul, sa valeur ;
   * plusieurs, leur moyenne avec leur nombre et leur plage. Rien sans capteur.
   */
  private _renderRoomSensors(): TemplateResult | typeof nothing {
    const areaId = this._config?.area_id;
    if (!this.hass || !areaId) {
      return nothing;
    }
    const s = roomSensors(this.hass, areaId);
    if (s.temperature === null && s.humidity === null) {
      return nothing;
    }
    const parts: string[] = [];
    if (s.temperature !== null) {
      parts.push(t(this.hass, "degree", { value: s.temperature }));
    }
    if (s.humidity !== null) {
      parts.push(t(this.hass, "humidity", { value: s.humidity }));
    }
    const n = Math.max(s.temperature_count, s.humidity_count);
    const caption =
      n <= 1
        ? t(this.hass, "area_room_sensor")
        : s.temperature_count > 1 && s.temperature_min !== s.temperature_max
          ? t(this.hass, "area_room_sensors_range", {
              n,
              min: s.temperature_min ?? "",
              max: s.temperature_max ?? "",
            })
          : t(this.hass, "area_room_sensors", { n });
    return html`
      <div class="room-sensor">
        ${ICON_THERMOMETER}
        <span class="room-sensor-value">${parts.join(" · ")}</span>
        <span class="room-sensor-label">${caption}</span>
      </div>
    `;
  }

  /** Climates de la zone hors pièce Ally de la carte (toutes intégrations). */
  private _renderAreaClimates(room: Room | undefined): TemplateResult {
    const hass = this.hass;
    const areaId = this._config?.area_id;
    const ids =
      hass && areaId
        ? climatesInArea(hass, areaId).filter((id) => id !== room?.climate_entity_id)
        : [];
    const views = ids
      .map((id) => (hass ? climateView(hass, id) : null))
      .filter((v): v is ClimateView => v !== null);
    if (views.length === 0 && room) {
      return html``;
    }
    return html`
      <div class="heads">
        <div class="heads-title">
          ${t(this.hass, room ? "area_other_climates" : "area_climates")}
        </div>
        ${views.length === 0
          ? html`<div class="hint">${t(this.hass, "area_no_climate")}</div>`
          : html`<div class="heads-list">${views.map((v) => this._renderClimateRow(v))}</div>`}
      </div>
    `;
  }

  private _renderClimateRow(view: ClimateView): TemplateResult {
    const deg = (v: number | null): string =>
      v === null ? "—" : t(this.hass, "degree", { value: v });
    const canAdjust =
      this._canWriteForeign && Boolean(this.hass?.callService) && canAdjustClimate(view);
    const busy = this._busyClimate !== null;
    const down = canAdjust ? steppedClimateTarget(view, -1) : null;
    const up = canAdjust ? steppedClimateTarget(view, 1) : null;
    const x = view.extras;
    const heating = view.available && view.action === "heating";
    // Tête qui régule sur un capteur externe : la température qui compte est la sienne ;
    // la mesure propre de la tête reste affichée, nommée comme telle.
    const external = x.external_temperature;
    const shown = external ?? view.current;
    return html`
      <div class="climate-row">
        <div class="row-top">
          <span class="head-name">${view.name}</span>
          <span class="row-now">
            <span class="row-temp ${heating ? "heating" : ""}">${deg(shown)}</span>
            ${view.available && view.action
              ? html`<span class="row-action">${actionLabel(this.hass, view.action)}</span>`
              : nothing}
          </span>
        </div>
        ${external !== null
          ? html`<div class="row-note">
              ${t(this.hass, "head_external_note", {
                head: deg(view.current),
              })}
            </div>`
          : nothing}
        <div class="row-bottom">
          <span class="badges">
            ${renderBadge(
              view.available ? "ok" : "off",
              view.available ? ICON_WIFI : ICON_WIFI_OFF,
              t(this.hass, view.available ? "head_online" : "head_offline"),
            )}
            ${x.battery !== null || x.low_battery
              ? renderBadge(
                  x.low_battery ? "warn" : "muted",
                  ICON_BATTERY,
                  x.battery === null
                    ? t(this.hass, "head_low_battery")
                    : t(this.hass, x.low_battery ? "head_low_battery" : "head_battery", {
                        value: x.battery,
                      }),
                )
              : nothing}
            ${x.valve_opening !== null
              ? renderBadge(
                  x.valve_opening > 0 ? "ok" : "muted",
                  ICON_VALVE,
                  t(this.hass, "head_valve", { value: x.valve_opening }),
                )
              : nothing}
            ${external !== null
              ? renderBadge(
                  "ok",
                  ICON_THERMOMETER,
                  t(this.hass, "head_external_sensor", { value: deg(external) }),
                )
              : nothing}
            ${x.window_open
              ? renderBadge("warn", ICON_WINDOW, t(this.hass, "head_window_open"))
              : nothing}
            ${x.heat_required
              ? renderBadge("ok", ICON_FLAME, t(this.hass, "head_heat_required"))
              : nothing}
            ${x.linkquality !== null
              ? renderBadge("muted", ICON_WIFI, t(this.hass, "head_linkquality", { value: x.linkquality }))
              : nothing}
            ${view.ally
              ? renderBadge("muted", ICON_LOCK, t(this.hass, "area_ally_climate"))
              : nothing}
          </span>
          <span class="setpoint">
            ${canAdjust
              ? html`<button
                  class="step small"
                  @click=${() => this._adjustClimate(view.entity_id, -1)}
                  ?disabled=${busy || down === null}
                  aria-label=${t(this.hass, "cooler")}
                  title=${t(this.hass, "cooler")}
                >
                  ${ICON_MINUS}
                </button>`
              : nothing}
            <span class="row-target">${deg(view.target)}</span>
            ${canAdjust
              ? html`<button
                  class="step small"
                  @click=${() => this._adjustClimate(view.entity_id, 1)}
                  ?disabled=${busy || up === null}
                  aria-label=${t(this.hass, "warmer")}
                  title=${t(this.hass, "warmer")}
                >
                  ${ICON_PLUS}
                </button>`
              : nothing}
          </span>
        </div>
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
      .step.small {
        width: 28px;
        height: 28px;
      }
      .step.small svg {
        width: 16px;
        height: 16px;
      }
      .climate-row {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 6px 0;
        border-top: 1px solid var(--divider-color, #eee);
      }
      .climate-row:first-child {
        border-top: none;
      }
      .row-top,
      .row-bottom {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
      }
      .row-now {
        display: inline-flex;
        align-items: baseline;
        gap: 6px;
      }
      .row-temp {
        font-size: 1.1rem;
        font-variant-numeric: tabular-nums;
        color: var(--primary-text-color);
      }
      .row-temp.heating {
        color: var(--danfoss-comfort-color, var(--primary-color, #ff8a33));
      }
      .row-action {
        font-size: 0.8rem;
        color: var(--secondary-text-color);
      }
      .row-note {
        font-size: 0.8rem;
        color: var(--secondary-text-color);
      }
      .room-sensor {
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
        color: var(--primary-text-color);
      }
      .room-sensor svg {
        width: 18px;
        height: 18px;
        fill: var(--secondary-text-color);
        align-self: center;
      }
      .room-sensor-value {
        font-size: 1.4rem;
        font-weight: 300;
        font-variant-numeric: tabular-nums;
      }
      .room-sensor-label {
        font-size: 0.85rem;
        color: var(--secondary-text-color);
      }
      .row-target {
        font-variant-numeric: tabular-nums;
        min-width: 3rem;
        text-align: center;
        color: var(--primary-text-color);
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-room-card": DanfossAllyRoomCard;
  }
}
