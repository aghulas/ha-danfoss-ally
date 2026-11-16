/**
 * Éditeur de configuration de `danfoss-ally-schedule-card` (lot 3).
 *
 * Choix de la pièce parmi `danfoss_ally_cloud/rooms`. Utilise un `<select>`
 * natif pour rester sans dépendance aux composants HA (la carte doit aussi
 * fonctionner dans la page de démo hors Home Assistant). Émet `config-changed`
 * comme attendu par l'éditeur de tableau de bord Lovelace.
 */
import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { t } from "./localize";
import type { HassLike, Room, ScheduleCardConfig } from "./types";
import { fetchRooms } from "./ws";

@customElement("danfoss-ally-schedule-card-editor")
export class DanfossAllyScheduleCardEditor extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;

  @state() private _config: ScheduleCardConfig = {};
  @state() private _rooms: Room[] = [];
  @state() private _loaded = false;

  public setConfig(config: ScheduleCardConfig): void {
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

  private _roomChanged(ev: Event): void {
    const value = (ev.target as HTMLSelectElement).value;
    const config: ScheduleCardConfig = { ...this._config, room_id: value };
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true,
      }),
    );
  }

  protected render(): TemplateResult {
    return html`
      <div class="editor">
        <label for="room">${t(this.hass, "pick_room")}</label>
        <select id="room" @change=${this._roomChanged}>
          <option value="" ?selected=${!this._config.room_id}>—</option>
          ${this._rooms.map(
            (room) => html`
              <option value=${room.id} ?selected=${room.id === this._config.room_id}>
                ${room.name}
              </option>
            `,
          )}
        </select>
        ${this._rooms.length === 0
          ? html`<div class="hint">${t(this.hass, "rooms_unavailable")}</div>`
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
    "danfoss-ally-schedule-card-editor": DanfossAllyScheduleCardEditor;
  }
}
