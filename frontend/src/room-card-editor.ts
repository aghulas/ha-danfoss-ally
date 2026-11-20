/**
 * Éditeur de configuration de `danfoss-ally-room-card` (axe D, §8.3).
 *
 * Deux choix exclusifs, par `<select>` natifs (sans dépendance aux composants HA,
 * pour rester utilisable dans la page de démo) : une pièce Danfoss Ally parmi
 * `danfoss_ally_cloud/rooms` (`room_id`), ou une zone Home Assistant qui contient au
 * moins un `climate` (`area_id`), toutes intégrations. Choisir l'un retire l'autre.
 * Émet `config-changed` comme attendu par l'éditeur de tableau de bord Lovelace.
 */
import { LitElement, type TemplateResult, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { type AreaClimates, areasWithClimates } from "./area";
import { t } from "./localize";
import type { HassLike, Room, RoomCardConfig } from "./types";
import { fetchRooms } from "./ws";

@customElement("danfoss-ally-room-card-editor")
export class DanfossAllyRoomCardEditor extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;

  @state() private _config: RoomCardConfig = {};
  @state() private _rooms: Room[] = [];
  @state() private _loaded = false;

  public setConfig(config: RoomCardConfig): void {
    this._config = { ...config };
  }

  protected updated(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }

  private async _load(): Promise<void> {
    if (this.hass) {
      this._rooms = await fetchRooms(this.hass);
    }
  }

  private get _areas(): AreaClimates[] {
    return this.hass ? areasWithClimates(this.hass) : [];
  }

  private _emit(config: RoomCardConfig): void {
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Une pièce choisie retire la zone (et inversement) : une seule source par carte. */
  private _pick(key: "room_id" | "area_id", value: string): void {
    const rest: RoomCardConfig = { ...this._config };
    delete rest.room_id;
    delete rest.area_id;
    this._emit(value ? { ...rest, [key]: value } : { ...rest, room_id: "" });
  }

  private _roomChanged(ev: Event): void {
    this._pick("room_id", (ev.target as HTMLSelectElement).value);
  }

  private _areaChanged(ev: Event): void {
    this._pick("area_id", (ev.target as HTMLSelectElement).value);
  }

  protected render(): TemplateResult {
    const areas = this._areas;
    const roomId = this._config.area_id ? "" : this._config.room_id;
    return html`
      <div class="editor">
        <div class="hint">${t(this.hass, "pick_hint")}</div>
        <label for="room">${t(this.hass, "pick_room")}</label>
        <select id="room" @change=${this._roomChanged}>
          <option value="" ?selected=${!roomId}>—</option>
          ${this._rooms.map(
            (room) => html`
              <option value=${room.id} ?selected=${room.id === roomId}>${room.name}</option>
            `,
          )}
        </select>
        ${this._rooms.length === 0
          ? html`<div class="hint">${t(this.hass, "rooms_unavailable")}</div>`
          : nothing}
        <label for="area">${t(this.hass, "pick_area")}</label>
        <select id="area" @change=${this._areaChanged}>
          <option value="" ?selected=${!this._config.area_id}>—</option>
          ${areas.map(
            (area) => html`
              <option value=${area.area_id} ?selected=${area.area_id === this._config.area_id}>
                ${area.name} (${area.entity_ids.length})
              </option>
            `,
          )}
        </select>
        ${areas.length === 0
          ? html`<div class="hint">${t(this.hass, "areas_unavailable")}</div>`
          : nothing}
      </div>
    `;
  }

  static styles = css`
    :host {
      display: block;
    }
    .editor {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 8px 0;
    }
    label {
      font-weight: 500;
      color: var(--primary-text-color);
      margin-top: 6px;
    }
    select {
      padding: 8px;
      border-radius: 6px;
      border: 1px solid var(--divider-color, #ccc);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #000);
      font: inherit;
    }
    .hint {
      color: var(--secondary-text-color);
      font-size: 0.9rem;
    }
  `;
}

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-room-card-editor": DanfossAllyRoomCardEditor;
  }
}
