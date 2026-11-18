/**
 * Panneau latéral `danfoss-ally-panel` (axe D, contrat §8.2) — vue d'ensemble du
 * bâtiment / de la flotte, en LECTURE SEULE.
 *
 * Par maison : badge vacances, passerelles et leur état, grille des pièces (santé :
 * têtes, hors ligne, batterie faible, demande de chauffe, fenêtre, incohérence,
 * défauts), relais de chaudière. Un bandeau de totaux donne la santé du bâtiment
 * d'un coup d'œil. N'appelle que la commande WebSocket `overview` (§5.3), jamais le
 * cloud, et se dégrade proprement.
 */
import { LitElement, type TemplateResult, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { t } from "./localize";
import type { FleetHome, FleetOverview, FleetRelay, FleetRoom, HassLike } from "./types";
import { CARD_VERSION } from "./version";
import { fetchOverview } from "./ws";

@customElement("danfoss-ally-panel")
export class DanfossAllyPanel extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;
  @property({ type: Boolean }) public narrow = false;

  @state() private _overview: FleetOverview | null = null;
  @state() private _loaded = false;
  @state() private _refreshing = false;

  protected updated(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }

  private async _load(): Promise<void> {
    if (this.hass) {
      this._overview = await fetchOverview(this.hass);
    }
  }

  private async _refresh(): Promise<void> {
    if (!this.hass || this._refreshing) {
      return;
    }
    this._refreshing = true;
    try {
      const overview = await fetchOverview(this.hass);
      if (overview) {
        this._overview = overview;
      }
    } finally {
      this._refreshing = false;
    }
  }

  protected render(): TemplateResult {
    const overview = this._overview;
    return html`
      <div class="page">
        <header class="bar">
          <h1>${t(this.hass, "panel_title")}</h1>
          <button class="refresh" @click=${this._refresh} ?disabled=${this._refreshing}>
            ${t(this.hass, "refresh")}
          </button>
        </header>
        ${overview ? this._renderBody(overview) : this._renderUnavailable()}
        <footer class="foot">${t(this.hass, "version", { version: CARD_VERSION })}</footer>
      </div>
    `;
  }

  private _renderUnavailable(): TemplateResult {
    return html`<div class="unavailable">${t(this.hass, "overview_unavailable")}</div>`;
  }

  private _renderBody(overview: FleetOverview): TemplateResult {
    const tot = overview.totals;
    return html`
      <section class="totals">
        ${this._stat(tot.rooms, t(this.hass, "fleet_rooms"), "")}
        ${this._stat(tot.heads, t(this.hass, "fleet_heads"), "")}
        ${this._stat(tot.gateways, t(this.hass, "fleet_gateways"), "")}
        ${this._stat(tot.offline, t(this.hass, "fleet_offline"), tot.offline ? "warn" : "")}
        ${this._stat(tot.low_battery, t(this.hass, "fleet_low_battery"), tot.low_battery ? "warn" : "")}
        ${this._stat(tot.heating, t(this.hass, "fleet_heating"), tot.heating ? "hot" : "")}
        ${this._stat(tot.faults, t(this.hass, "fleet_faults"), tot.faults ? "bad" : "")}
        ${this._stat(tot.relays_on, t(this.hass, "fleet_relays_on"), "")}
      </section>
      ${overview.homes.map((home) => this._renderHome(home))}
    `;
  }

  private _stat(value: number, label: string, kind: string): TemplateResult {
    return html`
      <div class="stat ${kind}">
        <span class="stat-value">${value}</span>
        <span class="stat-label">${label}</span>
      </div>
    `;
  }

  private _renderHome(home: FleetHome): TemplateResult {
    const onlineGw = home.gateways.filter((g) => g.online).length;
    return html`
      <section class="home">
        <div class="home-head">
          <h2>${home.name}</h2>
          <span class="tags">
            ${home.holiday_active
              ? html`<span class="tag holiday">${t(this.hass, "holiday_active")}</span>`
              : nothing}
            ${home.gateways.length > 0
              ? html`<span class="tag ${onlineGw === home.gateways.length ? "" : "warn"}">
                  ${t(this.hass, "gateway_online", {
                    n: `${onlineGw}/${home.gateways.length}`,
                  })}
                </span>`
              : nothing}
          </span>
        </div>
        <div class="rooms">${home.rooms.map((room) => this._renderRoom(room))}</div>
        ${home.relays.length > 0
          ? html`<div class="relays">${home.relays.map((relay) => this._renderRelay(relay))}</div>`
          : nothing}
      </section>
    `;
  }

  private _renderRoom(room: FleetRoom): TemplateResult {
    const healthy =
      room.offline === 0 && room.low_battery === 0 && room.faults === 0 && !room.window_open;
    return html`
      <div class="room ${healthy ? "ok" : "attn"}">
        <div class="room-top">
          <span class="room-name" title=${room.name}>${room.name}</span>
          <span class="heads-count">${room.head_count}×</span>
        </div>
        <div class="flags">
          ${room.heating ? html`<span class="flag hot">${t(this.hass, "room_calling")}</span>` : nothing}
          ${room.window_open ? html`<span class="flag warn">${t(this.hass, "room_window")}</span>` : nothing}
          ${room.offline ? html`<span class="flag warn">${t(this.hass, "room_offline_n", { n: room.offline })}</span>` : nothing}
          ${room.low_battery ? html`<span class="flag warn">${t(this.hass, "room_low_battery_n", { n: room.low_battery })}</span>` : nothing}
          ${room.faults ? html`<span class="flag bad">${t(this.hass, "room_faults_n", { n: room.faults })}</span>` : nothing}
          ${healthy ? html`<span class="flag ok">${t(this.hass, "room_ok")}</span>` : nothing}
        </div>
      </div>
    `;
  }

  private _renderRelay(relay: FleetRelay): TemplateResult {
    const on = relay.on === true;
    return html`
      <div class="relay">
        <span class="relay-dot ${on ? "on" : "off"}"></span>
        <span class="relay-name">${relay.name}</span>
        <span class="relay-state">${t(this.hass, on ? "relay_on" : "relay_off")}</span>
        <span class="relay-rooms">${t(this.hass, "rooms_calling", { n: relay.linked_rooms })}</span>
      </div>
    `;
  }

  static styles = css`
    :host {
      display: block;
      background: var(--primary-background-color, #f2f3f5);
      min-height: 100%;
    }
    .page {
      max-width: 1100px;
      margin: 0 auto;
      padding: 16px;
    }
    .bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    h1 {
      font-size: 1.4rem;
      font-weight: 500;
      color: var(--primary-text-color);
      margin: 8px 0 16px;
    }
    .refresh {
      cursor: pointer;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 16px;
      padding: 6px 14px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font: inherit;
      font-size: 0.85rem;
    }
    .refresh:disabled {
      opacity: 0.6;
      cursor: default;
    }
    .unavailable {
      color: var(--secondary-text-color);
      padding: 24px 0;
    }
    .totals {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 10px;
      margin-bottom: 20px;
    }
    .stat {
      background: var(--card-background-color, #fff);
      border-radius: 12px;
      padding: 12px 14px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .stat-value {
      font-size: 1.6rem;
      font-weight: 500;
      font-variant-numeric: tabular-nums;
      color: var(--primary-text-color);
    }
    .stat-label {
      font-size: 0.78rem;
      color: var(--secondary-text-color);
    }
    .stat.warn .stat-value {
      color: var(--warning-color, #ffa600);
    }
    .stat.bad .stat-value {
      color: var(--error-color, #c62828);
    }
    .stat.hot .stat-value {
      color: var(--danfoss-comfort-color, #ff8a33);
    }
    .home {
      background: var(--card-background-color, #fff);
      border-radius: 12px;
      padding: 14px 16px;
      margin-bottom: 16px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    }
    .home-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    h2 {
      font-size: 1.1rem;
      font-weight: 500;
      color: var(--primary-text-color);
      margin: 0 0 10px;
    }
    .tags {
      display: inline-flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .tag {
      font-size: 0.72rem;
      padding: 2px 8px;
      border-radius: 10px;
      background: var(--secondary-background-color, #eee);
      color: var(--primary-text-color);
    }
    .tag.holiday {
      background: var(--info-color, #39739d);
      color: var(--text-primary-color, #fff);
    }
    .tag.warn {
      background: var(--warning-color, #ffa600);
      color: var(--text-primary-color, #fff);
    }
    .rooms {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 8px;
    }
    .room {
      border: 1px solid var(--divider-color, #e8e8e8);
      border-radius: 10px;
      padding: 8px 10px;
    }
    .room.attn {
      border-color: var(--warning-color, #ffa600);
    }
    .room-top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    .room-name {
      font-size: 0.9rem;
      font-weight: 500;
      color: var(--primary-text-color);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .heads-count {
      font-size: 0.75rem;
      color: var(--secondary-text-color);
      font-variant-numeric: tabular-nums;
    }
    .flags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 6px;
    }
    .flag {
      font-size: 0.68rem;
      padding: 1px 7px;
      border-radius: 9px;
      background: var(--secondary-background-color, #eee);
      color: var(--secondary-text-color);
    }
    .flag.ok {
      color: var(--success-color, #2e7d32);
    }
    .flag.warn {
      background: var(--warning-color, #ffa600);
      color: var(--text-primary-color, #fff);
    }
    .flag.bad {
      background: var(--error-color, #c62828);
      color: var(--text-primary-color, #fff);
    }
    .flag.hot {
      background: var(--danfoss-comfort-color, #ff8a33);
      color: var(--text-primary-color, #fff);
    }
    .relays {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid var(--divider-color, #eee);
    }
    .relay {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.82rem;
      color: var(--primary-text-color);
    }
    .relay-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }
    .relay-dot.on {
      background: var(--danfoss-comfort-color, #ff8a33);
    }
    .relay-dot.off {
      background: var(--disabled-text-color, #9e9e9e);
    }
    .relay-rooms {
      color: var(--secondary-text-color);
      font-size: 0.78rem;
    }
    .foot {
      color: var(--secondary-text-color);
      font-size: 0.75rem;
      text-align: right;
      margin-top: 12px;
    }
  `;
}

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-panel": DanfossAllyPanel;
  }
}
