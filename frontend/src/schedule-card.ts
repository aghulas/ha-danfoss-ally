/**
 * Carte minimale `danfoss-ally-schedule-card` (lot 3).
 *
 * Affiche le nom de la pièce choisie et la version de la carte. Elle prépare le
 * terrain pour le lot 4 (lecture du programme) et le lot 5 (édition). Elle se
 * dégrade proprement si les commandes WebSocket du contrat §5.3 ne sont pas
 * encore disponibles (lot 2).
 */
import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import "./schedule-card-editor";
import { t } from "./localize";
import type { HassLike, Info, Room, ScheduleCardConfig } from "./types";
import { CARD_VERSION, needsReload } from "./version";
import { fetchInfo, fetchRooms, pickRoom } from "./ws";

@customElement("danfoss-ally-schedule-card")
export class DanfossAllyScheduleCard extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;

  @state() private _config?: ScheduleCardConfig;
  @state() private _rooms: Room[] = [];
  @state() private _info: Info | null = null;
  @state() private _loaded = false;

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
    return 3;
  }

  protected updated(changed: Map<string, unknown>): void {
    // Premier chargement des données dès que `hass` est disponible.
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }

  private async _load(): Promise<void> {
    if (!this.hass) {
      return;
    }
    const [info, rooms] = await Promise.all([
      fetchInfo(this.hass),
      fetchRooms(this.hass),
    ]);
    this._info = info;
    this._rooms = rooms;
  }

  private _reload(): void {
    // location peut être absent en test ; garde défensive.
    globalThis.location?.reload();
  }

  protected render(): TemplateResult {
    const room = pickRoom(this._rooms, this._config?.room_id);
    const title = this._roomTitle(room);
    const showReload = needsReload(CARD_VERSION, this._info?.version);
    const readOnly = this._info !== null && !this._info.is_admin;

    return html`
      <ha-card header="Danfoss Ally">
        <div class="content">
          ${showReload ? this._renderReloadBanner() : nothing}
          <div class="room">${title}</div>
          ${this._rooms.length === 0
            ? html`<div class="hint">${t(this.hass, "rooms_unavailable")}</div>`
            : nothing}
          ${readOnly
            ? html`<div class="hint">${t(this.hass, "read_only")}</div>`
            : nothing}
          <div class="version">${t(this.hass, "version", { version: CARD_VERSION })}</div>
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
    }
    .hint {
      margin-top: 8px;
      color: var(--secondary-text-color);
      font-size: 0.9rem;
    }
    .version {
      margin-top: 12px;
      color: var(--secondary-text-color);
      font-size: 0.8rem;
    }
    .reload {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
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

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-schedule-card": DanfossAllyScheduleCard;
  }
}
