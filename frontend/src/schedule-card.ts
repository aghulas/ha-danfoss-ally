/**
 * Carte `danfoss-ally-schedule-card` — lecture (lot 4) et écriture (lot 5) du
 * programme hebdomadaire d'une pièce Danfoss Ally.
 *
 * Lecture : nom de la pièce, consignes confort / réduit, grille des sept jours
 * avec les plages positionnées sur 24 h, état des têtes, bouton « actualiser ».
 *
 * Écriture (administrateur) : édition d'un jour (ajouter / déplacer / redimensionner
 * / supprimer une plage, saisie directe des heures au clavier et sur mobile),
 * validation immédiate (locale R1 + `schedule/validate`), compteur de transitions
 * « n / 6 », copie d'un jour vers d'autres, enregistrement des seuls jours modifiés,
 * suivi du lot par `jobs/subscribe`, bouton « revenir au programme » et garde des
 * modifications non enregistrées. Lecture seule si l'utilisateur n'est pas
 * administrateur (`is_admin` faux).
 *
 * En mode `embedded` (imbriqué dans `danfoss-ally-room-card`), la carte ouvre
 * directement l'éditeur de grille sans `<ha-card>` ni duplication du titre, des
 * consignes, des têtes et du pied de page, et émet `schedule-edit-close` à la
 * sortie d'édition.
 */
import { LitElement, type TemplateResult, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import {
  ICON_ALERT,
  ICON_CHECK,
  ICON_COPY,
  ICON_EDIT,
  ICON_MINUS,
  ICON_PLUS,
  ICON_RESTORE,
  ICON_SAVE,
  ICON_TRASH,
  ICON_WIFI,
  ICON_WIFI_OFF,
  ICON_WRENCH,
  cardSharedStyles,
  renderBadge,
  renderCardFooter,
  renderJobBanner,
  renderReadGrid,
  renderReloadBanner,
  renderScale,
  renderSetpoints,
} from "./card-shared";
import "./schedule-card-editor";
import {
  addRange,
  cloneDays,
  copyDay,
  deleteRange,
  modifiedDays,
  moveRange,
  resizeRange,
  setRangeTime,
  sortIndexedRanges,
  sortRanges,
} from "./edit";
import { dayLabel, errorText, t } from "./localize";
import { DAY_KEYS, type Bar, dayBars } from "./schedule";
import type {
  DayKey,
  HassLike,
  HeadState,
  Info,
  Room,
  Schedule,
  ScheduleCardConfig,
  Target,
  TimeRange,
  ValidateResponse,
  WriteJob,
} from "./types";
import { MAX_TRANSITIONS_PER_DAY, validateDay } from "./validate";
import { CARD_VERSION, needsReload } from "./version";
import {
  ScheduleCommandError,
  fetchInfo,
  fetchRooms,
  fetchSchedule,
  pickRoom,
  restoreSchedule,
  setSchedule,
  subscribeJobs,
  validateSchedule,
} from "./ws";

@customElement("danfoss-ally-schedule-card")
export class DanfossAllyScheduleCard extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;
  /** Mode imbriqué dans `danfoss-ally-room-card` : ouvre directement l'éditeur sans enrobage redondant. */
  @property({ type: Boolean }) public embedded = false;

  @state() private _config?: ScheduleCardConfig;
  @state() private _rooms: Room[] = [];
  @state() private _info: Info | null = null;
  @state() private _schedule: Schedule | null = null;
  @state() private _loaded = false;
  @state() private _refreshing = false;

  // --- Édition (lot 5) ---
  @state() private _editing = false;
  @state() private _draft: Record<DayKey, TimeRange[]> | null = null;
  @state() private _saving = false;
  @state() private _error: string | null = null;
  @state() private _job: WriteJob | null = null;
  @state() private _restoring = false;
  @state() private _copyFrom: DayKey | null = null;
  @state() private _copyTargets = new Set<DayKey>();
  @state() private _serverValidation: ValidateResponse | null = null;

  private _unsubscribe: (() => void) | null = null;
  private _validateTimer: ReturnType<typeof setTimeout> | null = null;
  private _drag?: {
    day: DayKey;
    index: number;
    mode: "move" | "start" | "end";
    startX: number;
    trackWidth: number;
    orig: TimeRange[];
  };

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
    // Changer de pièce abandonne une édition en cours (pas de fuite entre pièces).
    if (this._editing && config.room_id !== this._config?.room_id) {
      this._leaveEdit(false);
    }
    this._config = config;
  }

  public getCardSize(): number {
    return this._editing ? 12 : 6;
  }

  /** Démarre l'édition (appelable par un parent tel que `danfoss-ally-room-card`). */
  public beginEdit(): void {
    this._beginEdit();
  }

  /** Demande la sortie d'édition avec confirmation si des jours ont été modifiés. */
  public cancelEdit(): void {
    this._cancelEdit();
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._teardownDrag();
    globalThis.removeEventListener?.("beforeunload", this._onBeforeUnload);
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
      this.embedded ? Promise.resolve([] as Room[]) : fetchRooms(this.hass),
      target ? fetchSchedule(this.hass, target) : Promise.resolve(null),
    ]);
    this._info = info;
    if (!this.embedded) {
      this._rooms = rooms;
    }
    this._schedule = schedule;
    if (this.embedded && !this._editing && this._isAdmin && this._schedule) {
      this._beginEdit();
    }
    // Suivi des lots d'écriture (si la connexion WS le permet).
    if (!this._unsubscribe && !this.embedded) {
      this._unsubscribe = await subscribeJobs(this.hass, (job) => this._onJob(job));
    }
  }

  private _onJob(job: WriteJob): void {
    // Ne garder que les lots de la cible affichée.
    if (job.target?.id === this._config?.room_id) {
      this._job = job;
    }
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

  // --- Cycle d'édition ---

  private get _isAdmin(): boolean {
    // `info` absent (lot 2 non déployé) : on n'affiche pas l'écriture.
    return this._info !== null && this._info.is_admin;
  }

  private get _modified(): DayKey[] {
    if (!this._draft || !this._schedule) {
      return [];
    }
    return modifiedDays(this._schedule.days, this._draft, DAY_KEYS);
  }

  private get _allValid(): boolean {
    if (!this._draft) {
      return true;
    }
    return DAY_KEYS.every((day) => validateDay(this._draft![day] ?? [], day).valid);
  }

  private _beginEdit(): void {
    if (!this._schedule || !this._isAdmin) {
      return;
    }
    this._draft = cloneDays(this._schedule.days);
    this._editing = true;
    this._error = null;
    this._copyFrom = null;
    globalThis.addEventListener?.("beforeunload", this._onBeforeUnload);
  }

  private _leaveEdit(notifyParent = true): void {
    this._editing = false;
    this._draft = null;
    this._copyFrom = null;
    this._serverValidation = null;
    this._error = null;
    if (this._validateTimer) {
      clearTimeout(this._validateTimer);
      this._validateTimer = null;
    }
    globalThis.removeEventListener?.("beforeunload", this._onBeforeUnload);
    if (this.embedded && notifyParent) {
      this.dispatchEvent(
        new CustomEvent("schedule-edit-close", {
          detail: { schedule: this._schedule, job: this._job },
          bubbles: true,
          composed: true,
        }),
      );
    }
  }

  private _cancelEdit(): void {
    if (this._modified.length > 0) {
      const ok = globalThis.confirm?.(t(this.hass, "leave_confirm"));
      if (ok === false) {
        return;
      }
    }
    this._leaveEdit(true);
  }

  private readonly _onBeforeUnload = (ev: BeforeUnloadEvent): void => {
    if (this._editing && this._modified.length > 0) {
      ev.preventDefault();
      ev.returnValue = t(this.hass, "beforeunload");
    }
  };

  private _setDay(day: DayKey, ranges: TimeRange[]): void {
    if (!this._draft) {
      return;
    }
    this._draft = { ...this._draft, [day]: ranges };
    this._queueServerValidate();
  }

  /** Validation serveur (débatée) des jours modifiés, en plus de la locale. */
  private _queueServerValidate(): void {
    if (!this.hass) {
      return;
    }
    if (this._validateTimer) {
      clearTimeout(this._validateTimer);
    }
    this._validateTimer = setTimeout(() => {
      void this._runServerValidate();
    }, 300);
  }

  private async _runServerValidate(): Promise<void> {
    if (!this.hass || !this._draft) {
      return;
    }
    const days: Partial<Record<DayKey, TimeRange[]>> = {};
    for (const day of this._modified) {
      days[day] = this._draft[day];
    }
    this._serverValidation = await validateSchedule(this.hass, days);
  }

  // --- Opérations d'édition ---

  private _addRange(day: DayKey): void {
    if (!this._draft) {
      return;
    }
    this._setDay(day, addRange(this._draft[day] ?? []));
  }

  private _deleteRange(day: DayKey, index: number): void {
    if (!this._draft) {
      return;
    }
    this._setDay(day, deleteRange(this._draft[day] ?? [], index));
  }

  private _onTimeInput(day: DayKey, index: number, edge: "start" | "end", ev: Event): void {
    if (!this._draft) {
      return;
    }
    const value = (ev.target as HTMLInputElement).value;
    if (!value) {
      return;
    }
    this._setDay(day, setRangeTime(this._draft[day] ?? [], index, edge, value));
  }

  // --- Copier un jour ---

  private _openCopy(day: DayKey): void {
    this._copyFrom = this._copyFrom === day ? null : day;
    this._copyTargets = new Set();
  }

  private _toggleCopyTarget(day: DayKey): void {
    const next = new Set(this._copyTargets);
    if (next.has(day)) {
      next.delete(day);
    } else {
      next.add(day);
    }
    this._copyTargets = next;
  }

  private _toggleCopyAll(): void {
    if (!this._copyFrom) {
      return;
    }
    const others = DAY_KEYS.filter((d) => d !== this._copyFrom);
    this._copyTargets =
      this._copyTargets.size === others.length ? new Set() : new Set(others);
  }

  private _applyCopy(): void {
    if (!this._draft || !this._copyFrom || this._copyTargets.size === 0) {
      return;
    }
    this._draft = copyDay(this._draft, this._copyFrom, [...this._copyTargets]);
    this._copyFrom = null;
    this._copyTargets = new Set();
    this._queueServerValidate();
  }

  // --- Enregistrement / retour au programme ---

  private async _save(): Promise<void> {
    const target = this._target;
    if (!this.hass || !target || !this._draft || this._saving) {
      return;
    }
    const modified = this._modified;
    if (modified.length === 0 || !this._allValid) {
      return;
    }
    this._saving = true;
    this._error = null;
    const days: Partial<Record<DayKey, TimeRange[]>> = {};
    for (const day of modified) {
      days[day] = sortRanges(this._draft[day] ?? []);
    }
    try {
      const job = await setSchedule(this.hass, target, days);
      this._job = job;
      // Optimiste : le programme affiché reflète les jours envoyés.
      if (this._schedule) {
        this._schedule = { ...this._schedule, days: cloneDays(this._draft) };
      }
      this._leaveEdit(true);
    } catch (err) {
      const code = err instanceof ScheduleCommandError ? err.code : "unknown";
      this._error = errorText(this.hass, code, { max: MAX_TRANSITIONS_PER_DAY });
    } finally {
      this._saving = false;
    }
  }

  private async _restore(): Promise<void> {
    const target = this._target;
    if (!this.hass || !target || this._restoring) {
      return;
    }
    this._restoring = true;
    this._error = null;
    try {
      this._job = await restoreSchedule(this.hass, target);
    } catch (err) {
      const code = err instanceof ScheduleCommandError ? err.code : "unknown";
      this._error = errorText(this.hass, code);
    } finally {
      this._restoring = false;
    }
  }

  // --- Glisser-déposer (pointeur) : déplacer / redimensionner une plage ---

  private _onBarPointerDown(
    day: DayKey,
    index: number,
    mode: "move" | "start" | "end",
    ev: PointerEvent,
  ): void {
    if (!this._draft) {
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
    const handle = ev.currentTarget as HTMLElement;
    const track = handle.closest(".track") as HTMLElement | null;
    if (!track) {
      return;
    }
    this._drag = {
      day,
      index,
      mode,
      startX: ev.clientX,
      trackWidth: track.getBoundingClientRect().width || 1,
      orig: (this._draft[day] ?? []).map((r) => ({ ...r })),
    };
    handle.setPointerCapture?.(ev.pointerId);
    globalThis.addEventListener?.("pointermove", this._onDragMove);
    globalThis.addEventListener?.("pointerup", this._onDragEnd);
    globalThis.addEventListener?.("pointercancel", this._onDragEnd);
  }

  private readonly _onDragMove = (ev: PointerEvent): void => {
    if (!this._drag || !this._draft) {
      return;
    }
    const { day, index, mode, startX, trackWidth, orig } = this._drag;
    const deltaMin = ((ev.clientX - startX) / trackWidth) * 1440;
    const next =
      mode === "move" ? moveRange(orig, index, deltaMin) : resizeRange(orig, index, mode, deltaMin);
    this._setDay(day, next);
  };

  private readonly _onDragEnd = (): void => {
    if (this._drag && this._draft) {
      const day = this._drag.day;
      this._setDay(day, sortRanges(this._draft[day] ?? []));
    }
    this._teardownDrag();
  };

  private _teardownDrag(): void {
    this._drag = undefined;
    globalThis.removeEventListener?.("pointermove", this._onDragMove);
    globalThis.removeEventListener?.("pointerup", this._onDragEnd);
    globalThis.removeEventListener?.("pointercancel", this._onDragEnd);
  }

  // --- Rendu ---

  protected render(): TemplateResult {
    if (this.embedded) {
      return this._renderEmbedded();
    }
    const room = pickRoom(this._rooms, this._config?.room_id);
    const showReload = needsReload(CARD_VERSION, this._info?.version);
    const readOnly = this._info !== null && !this._info.is_admin;

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
          ${this._renderBody(room)}
        </div>
      </ha-card>
    `;
  }

  /** Rendu allégé quand l'éditeur est déplié dans `danfoss-ally-room-card`. */
  private _renderEmbedded(): TemplateResult {
    return html`
      <div class="embedded-editor">
        ${this._error ? html`<div class="banner error" role="alert">${this._error}</div>` : nothing}
        ${this._editing && this._draft
          ? html`
              <div class="embedded-bar">
                <span class="read-at">
                  ${this._modified.length > 0
                    ? t(this.hass, "unsaved_hint")
                    : t(this.hass, "no_changes")}
                </span>
                ${this._renderEditButtons()}
              </div>
              ${this._renderEditor()}
            `
          : html`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
      </div>
    `;
  }

  private _renderEditButtons(): TemplateResult {
    const canSave = this._modified.length > 0 && this._allValid && !this._saving;
    return html`
      <div class="actions">
        <button class="btn ghost" @click=${this._cancelEdit} ?disabled=${this._saving}>
          ${t(this.hass, "cancel")}
        </button>
        <button class="btn primary" @click=${this._save} ?disabled=${!canSave}>
          ${ICON_SAVE}<span>${this._saving ? t(this.hass, "saving") : t(this.hass, "save")}</span>
        </button>
      </div>
    `;
  }

  private _renderActions(room: Room | undefined): TemplateResult | typeof nothing {
    if (!this._isAdmin || !this._schedule) {
      return nothing;
    }
    if (this._editing) {
      return this._renderEditButtons();
    }
    const needsRestore = (room?.heads ?? []).some((h) => h.schedule_active === false);
    return html`
      <div class="actions">
        ${needsRestore
          ? html`<button
              class="btn ghost"
              @click=${this._restore}
              ?disabled=${this._restoring}
              title=${t(this.hass, "restore_hint")}
            >
              ${ICON_RESTORE}<span>${t(this.hass, "restore_schedule")}</span>
            </button>`
          : nothing}
        <button class="btn primary" @click=${this._beginEdit}>
          ${ICON_EDIT}<span>${t(this.hass, "edit")}</span>
        </button>
      </div>
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
      ${renderSetpoints(this.hass, comfort, setback)}
      ${this._editing && this._draft
        ? this._renderEditor()
        : schedule
          ? renderReadGrid(this.hass, schedule)
          : html`<div class="hint">${t(this.hass, "schedule_unavailable")}</div>`}
      ${this._renderHeads(room)}
      ${renderJobBanner(this.hass, this._job)}
      ${this._editing
        ? this._renderUnsavedHint()
        : renderCardFooter(
            this.hass,
            schedule,
            Boolean(this.hass && this._target),
            this._refreshing,
            () => void this._refresh(),
          )}
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

  // --- Grille d'édition (lot 5) ---

  private _renderEditor(): TemplateResult {
    return html`
      <div class="grid editing">
        ${renderScale()}
        ${DAY_KEYS.map((day) => this._renderEditDay(day))}
      </div>
    `;
  }

  private _renderEditDay(day: DayKey): TemplateResult {
    const ranges = this._draft![day] ?? [];
    const result = validateDay(ranges, day);
    const bars = dayBars(ranges);
    const counterClass = result.valid ? "counter" : "counter invalid";
    const codes = this._dayErrorCodes(day, result.errors.map((e) => e.code));
    const indexedRanges = sortIndexedRanges(ranges);
    return html`
      <div class="eday ${result.valid ? "" : "invalid"}">
        <div class="eday-row">
          <span class="day-label">${dayLabel(this.hass, day)}</span>
          <div class="track editable">
            ${bars.map((bar, i) => this._renderEditBar(day, i, bar))}
          </div>
          <span
            class=${counterClass}
            aria-label=${t(this.hass, "transitions_aria", {
              day: dayLabel(this.hass, day),
              n: result.transitions,
              max: MAX_TRANSITIONS_PER_DAY,
            })}
          >
            ${t(this.hass, "transitions_count", {
              n: result.transitions,
              max: MAX_TRANSITIONS_PER_DAY,
            })}
          </span>
        </div>
        <div class="ranges">
          ${indexedRanges.map(({ range, index }) => this._rangeRow(day, index, range))}
          <div class="range-tools">
            <button class="btn tiny" @click=${() => this._addRange(day)}>
              ${ICON_PLUS}<span>${t(this.hass, "add_range")}</span>
            </button>
            <button
              class="btn tiny"
              @click=${() => this._openCopy(day)}
              ?disabled=${ranges.length === 0 && (this._draft![day]?.length ?? 0) === 0}
              aria-expanded=${this._copyFrom === day ? "true" : "false"}
            >
              ${ICON_COPY}<span>${t(this.hass, "copy_day")}</span>
            </button>
          </div>
        </div>
        ${codes.length > 0
          ? html`<div class="errors">
              ${codes.map(
                (code) => html`<span class="err">${errorText(this.hass, code, {
                  max: MAX_TRANSITIONS_PER_DAY,
                })}</span>`,
              )}
            </div>`
          : result.impliedMidnight && result.transitions === MAX_TRANSITIONS_PER_DAY
            ? html`<div class="note">${t(this.hass, "midnight_note")}</div>`
            : nothing}
        ${this._copyFrom === day ? this._renderCopyPanel(day) : nothing}
      </div>
    `;
  }

  /** Codes d'erreur à afficher : union locale + serveur, sans doublon. */
  private _dayErrorCodes(day: DayKey, localCodes: string[]): string[] {
    const codes = new Set(localCodes);
    for (const e of this._serverValidation?.errors ?? []) {
      if (e.day === day) {
        codes.add(e.code);
      }
    }
    return [...codes];
  }

  private _renderEditBar(day: DayKey, index: number, bar: Bar): TemplateResult {
    return html`
      <div class="bar edit" style="left:${bar.leftPct}%;width:${bar.widthPct}%">
        <span
          class="grip start"
          @pointerdown=${(ev: PointerEvent) => this._onBarPointerDown(day, index, "start", ev)}
        ></span>
        <span
          class="grip body"
          @pointerdown=${(ev: PointerEvent) => this._onBarPointerDown(day, index, "move", ev)}
          title=${t(this.hass, "range_label", { start: bar.start, end: bar.end })}
        ></span>
        <span
          class="grip end"
          @pointerdown=${(ev: PointerEvent) => this._onBarPointerDown(day, index, "end", ev)}
        ></span>
      </div>
    `;
  }

  private _rangeRow(day: DayKey, index: number, r: TimeRange): TemplateResult {
    return html`
      <div class="range">
        <label class="field">
          <span class="field-label">${t(this.hass, "range_start")}</span>
          <input
            type="time"
            step="300"
            .value=${r.start}
            @change=${(ev: Event) => this._onTimeInput(day, index, "start", ev)}
          />
        </label>
        <span class="dash">–</span>
        <label class="field">
          <span class="field-label">${t(this.hass, "range_end")}</span>
          <input
            type="time"
            step="300"
            .value=${r.end}
            @change=${(ev: Event) => this._onTimeInput(day, index, "end", ev)}
          />
        </label>
        <button
          class="btn icon"
          @click=${() => this._deleteRange(day, index)}
          aria-label=${t(this.hass, "delete_range")}
          title=${t(this.hass, "delete_range")}
        >
          ${ICON_TRASH}
        </button>
      </div>
    `;
  }

  private _renderCopyPanel(day: DayKey): TemplateResult {
    const others = DAY_KEYS.filter((d) => d !== day);
    const allSelected = this._copyTargets.size === others.length;
    return html`
      <div class="copy-panel">
        <div class="copy-head">${t(this.hass, "copy_heading", { day: dayLabel(this.hass, day) })}</div>
        <div class="copy-days">
          <label class="copy-opt all">
            <input type="checkbox" .checked=${allSelected} @change=${this._toggleCopyAll} />
            <span>${t(this.hass, "copy_select_all")}</span>
          </label>
          ${others.map(
            (d) => html`
              <label class="copy-opt">
                <input
                  type="checkbox"
                  .checked=${this._copyTargets.has(d)}
                  @change=${() => this._toggleCopyTarget(d)}
                />
                <span>${dayLabel(this.hass, d)}</span>
              </label>
            `,
          )}
        </div>
        <div class="copy-actions">
          <button class="btn ghost tiny" @click=${() => this._openCopy(day)}>
            ${t(this.hass, "copy_cancel")}
          </button>
          <button
            class="btn primary tiny"
            @click=${this._applyCopy}
            ?disabled=${this._copyTargets.size === 0}
          >
            ${t(this.hass, "copy_apply")}
          </button>
        </div>
      </div>
    `;
  }

  private _renderUnsavedHint(): TemplateResult {
    const dirty = this._modified.length > 0;
    return html`
      <div class="footer edit-footer">
        <span class="read-at">${dirty ? t(this.hass, "unsaved_hint") : t(this.hass, "no_changes")}</span>
        <span class="version">${t(this.hass, "version", { version: CARD_VERSION })}</span>
      </div>
    `;
  }

  // --- Têtes ---

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
    const jobHead = this._job?.heads.find((h) => h.device_id === head.device_id);
    return html`
      <div class="head">
        <span class="head-name">${head.name}</span>
        <span class="badges">
          ${jobHead ? this._renderJobBadge(jobHead.status) : nothing}
          ${renderBadge(
            head.online ? "ok" : "off",
            head.online ? ICON_WIFI : ICON_WIFI_OFF,
            t(this.hass, head.online ? "head_online" : "head_offline"),
          )}
          ${head.schedule_active !== null
            ? renderBadge(
                head.schedule_active ? "ok" : "muted",
                head.schedule_active ? ICON_CHECK : ICON_MINUS,
                t(this.hass, head.schedule_active ? "head_schedule_on" : "head_schedule_off"),
              )
            : nothing}
          ${head.inconsistent
            ? renderBadge("warn", ICON_ALERT, t(this.hass, "head_inconsistent"))
            : nothing}
          ${head.mounting
            ? renderBadge("muted", ICON_WRENCH, t(this.hass, "head_mounting"))
            : nothing}
        </span>
      </div>
    `;
  }

  private _renderJobBadge(status: WriteJob["heads"][number]["status"]): TemplateResult {
    const map: Record<string, { kind: string; key: string }> = {
      pending: { kind: "muted", key: "head_job_pending" },
      applied: { kind: "ok", key: "head_job_applied" },
      mismatch: { kind: "warn", key: "head_job_mismatch" },
      unreachable: { kind: "off", key: "head_job_unreachable" },
      unverified: { kind: "muted", key: "head_job_unverified" },
    };
    const m = map[status] ?? map.pending;
    const label = t(this.hass, m.key as Parameters<typeof t>[1]);
    return html`<span class="pill ${m.kind}" title=${label}>${label}</span>`;
  }

  static styles = [
    cardSharedStyles,
    css`
      .setpoints {
        margin: 12px 0;
      }
      .embedded-editor {
        margin: 8px 0;
        padding-top: 8px;
        border-top: 1px solid var(--divider-color, #eee);
      }
      .embedded-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 6px;
      }
      .track.editable {
        height: 22px;
        overflow: visible;
      }
      .bar.edit {
        display: flex;
        touch-action: none;
      }
      .grip {
        display: block;
      }
      .grip.body {
        flex: 1 1 auto;
        cursor: grab;
      }
      .grip.start,
      .grip.end {
        flex: 0 0 8px;
        cursor: ew-resize;
        background: rgba(0, 0, 0, 0.25);
      }
      .grip.start {
        border-radius: 3px 0 0 3px;
      }
      .grip.end {
        border-radius: 0 3px 3px 0;
      }
      .eday {
        padding: 6px 0;
        border-bottom: 1px solid var(--divider-color, #eee);
      }
      .eday.invalid {
        background: var(--danfoss-invalid-bg, rgba(198, 40, 40, 0.06));
        border-radius: 6px;
      }
      .eday-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .counter {
        flex: 0 0 auto;
        font-size: 0.75rem;
        font-variant-numeric: tabular-nums;
        color: var(--secondary-text-color);
        min-width: 2.4rem;
        text-align: right;
      }
      .counter.invalid {
        color: var(--error-color, #c62828);
        font-weight: 600;
      }
      .ranges {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin: 6px 0 0 calc(2.6rem + 8px);
      }
      .range {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .field {
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }
      .field-label {
        font-size: 0.7rem;
        color: var(--secondary-text-color);
      }
      input[type="time"] {
        font: inherit;
        font-size: 0.85rem;
        padding: 4px 6px;
        border-radius: 6px;
        border: 1px solid var(--divider-color, #ccc);
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color, #000);
        color-scheme: light dark;
      }
      .dash {
        color: var(--secondary-text-color);
      }
      .range-tools {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 2px;
      }
      .errors {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 6px 0 0 calc(2.6rem + 8px);
      }
      .err {
        font-size: 0.75rem;
        color: var(--error-color, #c62828);
      }
      .note {
        font-size: 0.72rem;
        color: var(--secondary-text-color);
        margin: 6px 0 0 calc(2.6rem + 8px);
      }
      .copy-panel {
        margin: 8px 0 2px calc(2.6rem + 8px);
        padding: 8px 10px;
        border-radius: 8px;
        background: var(--secondary-background-color, #f3f3f3);
      }
      .copy-head {
        font-size: 0.8rem;
        font-weight: 500;
        margin-bottom: 6px;
      }
      .copy-days {
        display: flex;
        flex-wrap: wrap;
        gap: 4px 12px;
      }
      .copy-opt {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 0.8rem;
        color: var(--primary-text-color);
      }
      .copy-opt.all {
        font-weight: 500;
        flex: 0 0 100%;
      }
      .copy-actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 8px;
      }
      @media (max-width: 480px) {
        .range {
          gap: 6px;
        }
        .ranges,
        .errors,
        .note,
        .copy-panel {
          margin-left: 0;
        }
      }
    `,
  ];
}

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-schedule-card": DanfossAllyScheduleCard;
  }
}
