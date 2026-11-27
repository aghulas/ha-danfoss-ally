/**
 * Panneau latéral `danfoss-ally-panel` (axe D, contrat §8.2) — vue d'ensemble du
 * bâtiment / de la flotte, en LECTURE SEULE.
 *
 * Par maison : badge vacances, passerelles et leur état, grille des pièces (santé :
 * têtes, hors ligne, batterie faible, demande de chauffe, fenêtre, incohérence,
 * défauts, température → consigne), relais de chaudière. Les pièces d'une seule
 * tête (sans groupe, contrat §3.6) sont dans la même grille, marquées « 1× » et
 * « tête seule ». Un bandeau de totaux donne la santé du bâtiment d'un coup d'œil.
 * N'appelle que la commande WebSocket `overview` (§5.3), jamais le cloud, et se
 * dégrade proprement.
 *
 * Navigation (§8.2) : chaque tuile de pièce est un lien vers la page de la pièce
 * (`/room/<id>` sous le préfixe du panneau), avec un fil d'Ariane pour revenir. La
 * page d'une pièce groupée embarque la carte pièce (§8.1) telle quelle : le panneau
 * n'ajoute AUCUN chemin d'écriture, les seules actions sont celles de cette carte,
 * avec ses règles. Une pièce d'une seule tête n'a pas de réglage de pièce : sa page
 * est en lecture seule.
 *
 * Éléments (§8.2) : la page d'une pièce liste ses têtes ; têtes, relais et passerelles
 * ont chacun une page (`/device/<id>`) avec leur état connu et les entités de leur
 * appareil Home Assistant, par groupe (commandes et mesures, réglages, diagnostic).
 * Une ligne d'entité n'écrit rien : elle ouvre la fenêtre d'entité de Home Assistant
 * (`hass-more-info`), où l'entité garde ses propres règles.
 *
 * Sous les pièces de l'intégration, une section « autres zones » (§8.3, affichable
 * ou non par un bouton, affichée par défaut) résume, zone HA par zone, les `climate`
 * des AUTRES intégrations (p. ex. des têtes appairées à Zigbee2MQTT), lus dans les
 * registres du frontend. Lecture seule, comme le reste du panneau.
 */
import { LitElement, type TemplateResult, css, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { type AreaClimates, areaClimateLine, areaSummary, areasWithClimates } from "./area";
import { climateLine, headNameHint, isHealthy, isSingleHead, namedAfterHead } from "./fleet";
import {
  ENTITY_GROUPS,
  type EntityRow,
  type PanelElement,
  deviceEntities,
  entityCount,
  findElement,
  haDeviceId,
  roomDeviceIdent,
  roomHeads,
  roomSensors,
  unplacedSensors,
} from "./element";
import { modeLabel, t } from "./localize";
import {
  FLEET_PATH,
  type PanelRoute,
  elementPath,
  findRoom,
  parsePath,
  roomPath,
} from "./nav";
import "./room-card";
import type {
  FleetHome,
  FleetOverview,
  FleetRelay,
  FleetRoom,
  FleetSensor,
  HassLike,
  Room,
  RoomCardConfig,
} from "./types";
import { CARD_VERSION } from "./version";
import { fetchOverview, fetchRooms } from "./ws";

@customElement("danfoss-ally-panel")
export class DanfossAllyPanel extends LitElement {
  @property({ attribute: false }) public hass?: HassLike;
  @property({ type: Boolean }) public narrow = false;
  /** Route donnée par Home Assistant (`{ prefix, path }`) ; absente dans la démo. */
  @property({ attribute: false }) public route?: PanelRoute;

  @state() private _overview: FleetOverview | null = null;
  /** Pièces et leurs têtes (`rooms`) : alimente les pages de pièce et d'élément. */
  @state() private _rooms: Room[] = [];
  @state() private _loaded = false;
  @state() private _refreshing = false;
  @state() private _showOtherAreas = readShowOtherAreas();
  /** `path` courant sous le préfixe du panneau (suit `route`, ou la navigation interne). */
  @state() private _path = FLEET_PATH;
  /** Carte pièce embarquée dans la page d'une pièce, et la pièce qu'elle montre. */
  private _roomCard?: EmbeddedRoomCard;
  private _roomCardId?: string;

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("route")) {
      this._path = this.route?.path ?? FLEET_PATH;
    }
  }

  protected updated(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      void this._load();
    }
  }

  private async _load(): Promise<void> {
    if (this.hass) {
      const [overview, rooms] = await Promise.all([fetchOverview(this.hass), fetchRooms(this.hass)]);
      this._overview = overview;
      this._rooms = rooms;
    }
  }

  private async _refresh(): Promise<void> {
    if (!this.hass || this._refreshing) {
      return;
    }
    this._refreshing = true;
    try {
      const [overview, rooms] = await Promise.all([
        fetchOverview(this.hass),
        fetchRooms(this.hass),
      ]);
      if (overview) {
        this._overview = overview;
        this._rooms = rooms;
      }
    } finally {
      this._refreshing = false;
    }
  }

  /** Adresse d'un niveau, pour l'attribut `href` (clic milieu, copie du lien). */
  private _href(path: string): string {
    return this.route ? `${this.route.prefix}${path}` : "#";
  }

  /**
   * Va à un niveau du panneau. Dans Home Assistant : entrée d'historique + événement
   * `location-changed`, que le routeur de HA traduit en nouvelle `route` (le bouton
   * retour du navigateur marche donc). Hors HA (démo, tests) : état interne seul.
   */
  private _navigate(path: string, ev?: Event): void {
    const mouse = ev as MouseEvent | undefined;
    if (mouse && (mouse.ctrlKey || mouse.metaKey || mouse.shiftKey || mouse.button > 0)) {
      return; // nouvel onglet / fenêtre : laisser faire le navigateur
    }
    ev?.preventDefault();
    if (path === this._path) {
      return;
    }
    this._path = path;
    if (this.route && typeof history !== "undefined" && typeof window !== "undefined") {
      history.pushState(null, "", `${this.route.prefix}${path}`);
      window.dispatchEvent(
        new CustomEvent("location-changed", {
          detail: { replace: false },
          bubbles: true,
          composed: true,
        }),
      );
    }
  }

  private _toggleOtherAreas(): void {
    this._showOtherAreas = !this._showOtherAreas;
    writeShowOtherAreas(this._showOtherAreas);
  }

  protected render(): TemplateResult {
    const overview = this._overview;
    const view = parsePath(this._path);
    if (view.view !== "room") {
      this._roomCard = undefined;
      this._roomCardId = undefined;
    }
    return html`
      <div class="page">
        <header class="bar">
          <h1>${t(this.hass, "panel_title")}</h1>
          <span class="bar-actions">
            ${view.view === "fleet"
              ? html`<button
                  class="refresh toggle ${this._showOtherAreas ? "on" : ""}"
                  role="switch"
                  aria-checked=${this._showOtherAreas ? "true" : "false"}
                  @click=${this._toggleOtherAreas}
                >
                  ${t(this.hass, "panel_show_other_areas")}
                </button>`
              : nothing}
            <button class="refresh" @click=${this._refresh} ?disabled=${this._refreshing}>
              ${t(this.hass, "refresh")}
            </button>
          </span>
        </header>
        ${view.view === "room"
          ? this._renderRoomPage(overview, view.roomId)
          : view.view === "element"
            ? this._renderElementPage(overview, view.deviceId)
            : html`${overview ? this._renderBody(overview) : this._renderUnavailable()}
            ${this._showOtherAreas ? this._renderOtherAreas() : nothing}`}
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
        ${home.gateways.length > 0
          ? html`<div class="relays">
              ${home.gateways.map((gw) =>
                this._renderChip(
                  gw.device_id,
                  gw.online ? "on-ok" : "offline",
                  gw.name,
                  t(this.hass, gw.online ? "head_online" : "head_offline"),
                  !gw.online,
                ),
              )}
            </div>`
          : nothing}
        ${unplacedSensors(home).length > 0
          ? html`<div class="relays">
              ${unplacedSensors(home).map((sensor) =>
                this._renderChip(
                  sensor.device_id,
                  sensor.online ? "on-ok" : "offline",
                  sensor.name,
                  sensor.online && sensor.temperature !== null
                    ? t(this.hass, "el_temperature", { value: sensor.temperature })
                    : t(this.hass, sensor.online ? "head_online" : "head_offline"),
                  !sensor.online,
                  t(this.hass, "el_kind_sensor"),
                ),
              )}
            </div>`
          : nothing}
      </section>
    `;
  }

  private _renderRoom(room: FleetRoom): TemplateResult {
    const healthy = isHealthy(room);
    const single = isSingleHead(room);
    const hint = headNameHint(room);
    const climate = climateLine(room);
    const title = hint ? `${room.name} — ${hint}` : room.name;
    const path = roomPath(room.id);
    return html`
      <a
        class="room link ${healthy ? "ok" : "attn"} ${single ? "single" : ""}"
        href=${this._href(path)}
        @click=${(ev: Event) => this._navigate(path, ev)}
      >
        <div class="room-top">
          <span class="room-name" title=${title}>${room.name}</span>
          <span class="heads-count">${room.head_count}×</span>
        </div>
        ${hint ? html`<div class="room-sub" title=${hint}>${hint}</div>` : nothing}
        ${single
          ? html`<div class="room-sub kind">
              ${namedAfterHead(room)
                ? t(this.hass, "room_named_after_head")
                : t(this.hass, "room_single_head")}
            </div>`
          : nothing}
        ${climate ? html`<div class="room-climate">${climate}</div>` : nothing}
        ${this._renderFlags(room)}
      </a>
    `;
  }

  private _renderFlags(room: FleetRoom): TemplateResult {
    return html`
      <div class="flags">
        ${room.heating ? html`<span class="flag hot">${t(this.hass, "room_calling")}</span>` : nothing}
        ${room.window_open ? html`<span class="flag warn">${t(this.hass, "room_window")}</span>` : nothing}
        ${room.offline ? html`<span class="flag warn">${t(this.hass, "room_offline_n", { n: room.offline })}</span>` : nothing}
        ${room.low_battery ? html`<span class="flag warn">${t(this.hass, "room_low_battery_n", { n: room.low_battery })}</span>` : nothing}
        ${room.faults ? html`<span class="flag bad">${t(this.hass, "room_faults_n", { n: room.faults })}</span>` : nothing}
        ${isHealthy(room) ? html`<span class="flag ok">${t(this.hass, "room_ok")}</span>` : nothing}
      </div>
    `;
  }

  /** Fil d'Ariane : bâtiment (lien) › maison › pièce. */
  private _renderCrumbs(trail: Crumb[]): TemplateResult {
    return html`
      <nav class="crumbs" aria-label=${t(this.hass, "nav_breadcrumb")}>
        <a
          class="crumb-link"
          href=${this._href(FLEET_PATH)}
          @click=${(ev: Event) => this._navigate(FLEET_PATH, ev)}
          >${t(this.hass, "nav_building")}</a
        >
        ${trail.map((crumb, i) => {
          const path = crumb.path;
          return html`<span class="crumb-sep" aria-hidden="true">›</span>
            ${path !== undefined
              ? html`<a
                  class="crumb-link"
                  href=${this._href(path)}
                  @click=${(ev: Event) => this._navigate(path, ev)}
                  >${crumb.label}</a
                >`
              : html`<span class="crumb" aria-current=${i === trail.length - 1 ? "page" : nothing}
                  >${crumb.label}</span
                >`}`;
        })}
      </nav>
    `;
  }

  /** Page d'une pièce (§8.2) : fil d'Ariane, santé, puis la carte pièce (§8.1) si elle a un groupe. */
  private _renderRoomPage(overview: FleetOverview | null, roomId: string): TemplateResult {
    if (!overview) {
      return html`${this._renderCrumbs([])}${this._renderUnavailable()}`;
    }
    const found = findRoom(overview, roomId);
    if (!found) {
      return html`${this._renderCrumbs([])}
        <div class="unavailable">${t(this.hass, "nav_room_not_found")}</div>`;
    }
    const { home, room } = found;
    const single = isSingleHead(room);
    const hint = headNameHint(room);
    const climate = climateLine(room);
    return html`
      ${this._renderCrumbs([{ label: home.name }, { label: room.name }])}
      <section class="home room-page">
        <div class="home-head">
          <h2>${room.name}</h2>
          <span class="heads-count">${t(this.hass, "nav_heads_n", { n: room.head_count })}</span>
        </div>
        ${hint ? html`<div class="room-sub">${hint}</div>` : nothing}
        ${climate ? html`<div class="room-climate">${climate}</div>` : nothing}
        ${this._renderFlags(room)}
        ${single
          ? html`<div class="room-sub wrap note">${t(this.hass, "nav_single_head_note")}</div>`
          : nothing}
      </section>
      ${single ? nothing : html`<div class="room-card-slot">${this._embeddedRoomCard(room.id)}</div>`}
      ${this._renderRoomElements(home, room)}
      ${single
        ? nothing
        : this._renderEntities(haDeviceId(this.hass, roomDeviceIdent(room.id)), "el_room_entities", false)}
    `;
  }

  /** Résumé d'un capteur de pièce : mesures (si connues), batterie. */
  private _sensorFlags(sensor: FleetSensor): TemplateResult {
    return html`
      ${sensor.online
        ? html`<span class="flag ok">${t(this.hass, "head_online")}</span>`
        : html`<span class="flag warn">${t(this.hass, "head_offline")}</span>`}
      ${sensor.temperature !== null
        ? html`<span class="flag">${t(this.hass, "el_temperature", { value: sensor.temperature })}</span>`
        : nothing}
      ${sensor.humidity !== null
        ? html`<span class="flag">${t(this.hass, "el_humidity", { value: sensor.humidity })}</span>`
        : nothing}
      ${sensor.battery !== null
        ? html`<span class="flag">${t(this.hass, "head_battery", { value: sensor.battery })}</span>`
        : nothing}
    `;
  }

  /** Têtes et capteurs de la pièce, chacun un lien vers sa page. */
  private _renderRoomElements(home: FleetHome, room: FleetRoom): TemplateResult | typeof nothing {
    const heads = roomHeads(room, this._rooms);
    const sensors = roomSensors(home, room.id);
    if (heads.length === 0 && sensors.length === 0) {
      return nothing;
    }
    return html`
      <section class="home">
        <div class="home-head"><h2>${t(this.hass, "el_elements")}</h2></div>
        <div class="rooms">
          ${heads.map((h) => {
            const path = elementPath(h.id, room.id);
            const head = h.head;
            return html`
              <a
                class="room link ${h.online ? "ok" : "attn"}"
                href=${this._href(path)}
                @click=${(ev: Event) => this._navigate(path, ev)}
              >
                <div class="room-top">
                  <span class="room-name" title=${h.name}>${h.name}</span>
                </div>
                <div class="room-sub">${t(this.hass, "el_kind_head")}</div>
                <div class="flags">
                  ${h.online
                    ? html`<span class="flag ok">${t(this.hass, "head_online")}</span>`
                    : html`<span class="flag warn">${t(this.hass, "head_offline")}</span>`}
                  ${head && head.battery !== null
                    ? html`<span class="flag">${t(this.hass, "head_battery", { value: head.battery })}</span>`
                    : nothing}
                  ${head?.window_open
                    ? html`<span class="flag warn">${t(this.hass, "head_window_open")}</span>`
                    : nothing}
                  ${head && head.faults.length > 0
                    ? html`<span class="flag bad">${t(this.hass, "room_faults_n", { n: head.faults.length })}</span>`
                    : nothing}
                </div>
              </a>
            `;
          })}
          ${sensors.map((sensor) => {
            const path = elementPath(sensor.device_id);
            return html`
              <a
                class="room link ${sensor.online ? "ok" : "attn"}"
                href=${this._href(path)}
                @click=${(ev: Event) => this._navigate(path, ev)}
              >
                <div class="room-top">
                  <span class="room-name" title=${sensor.name}>${sensor.name}</span>
                </div>
                <div class="room-sub">${t(this.hass, "el_kind_sensor")}</div>
                <div class="flags">${this._sensorFlags(sensor)}</div>
              </a>
            `;
          })}
        </div>
      </section>
    `;
  }

  /** Page d'un élément (§8.2) : fil d'Ariane, état connu, entités de son appareil HA. */
  private _renderElementPage(
    overview: FleetOverview | null,
    deviceId: string,
  ): TemplateResult {
    if (!overview) {
      return html`${this._renderCrumbs([])}${this._renderUnavailable()}`;
    }
    const el = findElement(overview, this._rooms, deviceId);
    if (!el) {
      return html`${this._renderCrumbs([])}
        <div class="unavailable">${t(this.hass, "nav_element_not_found")}</div>`;
    }
    const trail: Crumb[] = [{ label: el.home.name }];
    if (el.kind === "head") {
      // La pièce de la tête fait foi, pas celle de l'adresse (lien périmé, tête déplacée).
      trail.push({ label: el.room.name, path: roomPath(el.room.id) });
    } else if (el.kind === "sensor" && el.room) {
      trail.push({ label: el.room.name, path: roomPath(el.room.id) });
    }
    trail.push({ label: el.name });
    const kindKey = (
      {
        head: "el_kind_head",
        sensor: "el_kind_sensor",
        relay: "el_kind_relay",
        gateway: "el_kind_gateway",
      } as const
    )[el.kind];
    return html`
      ${this._renderCrumbs(trail)}
      <section class="home room-page">
        <div class="home-head">
          <h2>${el.name}</h2>
          <span class="heads-count">${t(this.hass, kindKey)}</span>
        </div>
        <div class="flags">${this._elementFlags(el)}</div>
      </section>
      ${this._renderEntities(haDeviceId(this.hass, el.id), "el_state", true)}
    `;
  }

  /** État connu d'un élément, tiré de `overview` / `rooms` (jamais supposé). */
  private _elementFlags(el: PanelElement): TemplateResult {
    const online = el.online
      ? html`<span class="flag ok">${t(this.hass, "head_online")}</span>`
      : html`<span class="flag warn">${t(this.hass, "head_offline")}</span>`;
    if (el.kind === "sensor") {
      return this._sensorFlags(el.sensor);
    }
    if (el.kind === "relay") {
      // Hors ligne, le marche/arrêt est le dernier état connu : il n'est pas affiché.
      return html`${online}
        ${el.online && el.relay.on !== null
          ? html`<span class="flag ${el.relay.on ? "hot" : ""}"
              >${t(this.hass, el.relay.on ? "relay_on" : "relay_off")}</span
            >`
          : nothing}
        <span class="flag">${t(this.hass, "rooms_linked", { n: el.relay.linked_rooms })}</span>`;
    }
    if (el.kind === "gateway") {
      const gw = el.gateway;
      return html`${online}
        ${gw.head_count !== undefined || gw.relay_count !== undefined
          ? html`<span class="flag"
              >${t(this.hass, "el_carries", {
                heads: gw.head_count ?? 0,
                relays: gw.relay_count ?? 0,
              })}</span
            >`
          : nothing}`;
    }
    const head = el.head;
    if (!head) {
      return html`${online}`;
    }
    return html`${online}
      <span class="flag">${modeLabel(this.hass, head.mode_displayed)}</span>
      ${head.schedule_active === null
        ? nothing
        : html`<span class="flag ${head.schedule_active ? "" : "warn"}"
            >${t(this.hass, head.schedule_active ? "head_schedule_on" : "head_schedule_off")}</span
          >`}
      ${head.inconsistent
        ? html`<span class="flag warn">${t(this.hass, "head_inconsistent")}</span>`
        : nothing}
      ${head.mounting ? html`<span class="flag warn">${t(this.hass, "head_mounting")}</span>` : nothing}
      ${head.battery !== null
        ? html`<span class="flag">${t(this.hass, "head_battery", { value: head.battery })}</span>`
        : nothing}
      ${head.valve_opening !== null
        ? html`<span class="flag">${t(this.hass, "head_valve", { value: head.valve_opening })}</span>`
        : nothing}
      ${head.heat_request === null
        ? nothing
        : html`<span class="flag ${head.heat_request ? "hot" : ""}"
            >${t(this.hass, head.heat_request ? "el_heat_request" : "el_no_heat_request")}</span
          >`}
      ${head.window_open === null
        ? nothing
        : html`<span class="flag ${head.window_open ? "warn" : ""}"
            >${t(this.hass, head.window_open ? "head_window_open" : "el_window_closed")}</span
          >`}
      ${head.child_lock ? html`<span class="flag">${t(this.hass, "head_child_lock")}</span>` : nothing}
      ${head.faults.map(
        (f) =>
          html`<span class="flag bad" title=${f.action ?? ""}
            >${t(this.hass, "head_fault", { code: f.code })}${f.label ? ` — ${f.label}` : ""}</span
          >`,
      )}`;
  }

  /**
   * Entités d'un appareil HA, par groupe. `explain` : dit pourquoi il n'y a rien (pas
   * d'appareil, pas d'entité) ; sinon la section est simplement absente.
   */
  private _renderEntities(
    deviceId: string | null,
    titleKey: "el_state" | "el_room_entities",
    explain: boolean,
  ): TemplateResult | typeof nothing {
    const groups = deviceId ? deviceEntities(this.hass, deviceId) : null;
    if (!groups || entityCount(groups) === 0) {
      return explain
        ? html`<div class="unavailable">
            ${t(this.hass, deviceId ? "el_no_entities" : "el_no_device")}
          </div>`
        : nothing;
    }
    const titled = titleKey === "el_room_entities";
    return html`
      ${titled ? html`<h2 class="section-title">${t(this.hass, titleKey)}</h2>` : nothing}
      <div class="room-sub wrap">${t(this.hass, "el_entities_hint")}</div>
      ${ENTITY_GROUPS.filter((g) => groups[g].length > 0).map(
        (g) => html`
          <section class="home">
            <div class="home-head"><h2>${t(this.hass, `el_group_${g}`)}</h2></div>
            <div class="ent-list">${groups[g].map((row) => this._renderEntityRow(row))}</div>
          </section>
        `,
      )}
    `;
  }

  private _renderEntityRow(row: EntityRow): TemplateResult {
    const stateObj = this.hass?.states?.[row.entity_id];
    const value = !row.available
      ? t(this.hass, "el_unavailable")
      : stateObj && this.hass?.formatEntityState
        ? this.hass.formatEntityState(stateObj)
        : `${row.state}${row.unit ? ` ${row.unit}` : ""}`;
    return html`
      <button
        class="ent-row ${row.available ? "" : "ent-off"}"
        @click=${() => this._moreInfo(row.entity_id)}
      >
        <span class="ent-name">${row.name}</span>
        <span class="ent-state">${value}</span>
      </button>
    `;
  }

  /** Ouvre la fenêtre d'entité de Home Assistant (lecture, et réglage par l'entité elle-même). */
  private _moreInfo(entityId: string): void {
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Pastille d'un relais ou d'une passerelle : lien vers sa page. */
  private _renderChip(
    deviceId: string,
    dot: string,
    name: string,
    stateLabel: string,
    offline: boolean,
    extra: string | null = null,
  ): TemplateResult {
    const path = elementPath(deviceId);
    return html`
      <a
        class="relay chip ${offline ? "relay-offline" : ""}"
        href=${this._href(path)}
        @click=${(ev: Event) => this._navigate(path, ev)}
      >
        <span class="relay-dot ${dot}"></span>
        <span class="relay-name">${name}</span>
        <span class="relay-state">${stateLabel}</span>
        ${extra ? html`<span class="relay-rooms">${extra}</span>` : nothing}
      </a>
    `;
  }

  /**
   * Carte pièce de la page : une seule instance par pièce affichée (créée à la main car
   * sa configuration passe par `setConfig`), à qui `hass` est repassé à chaque rendu.
   */
  private _embeddedRoomCard(roomId: string): EmbeddedRoomCard | typeof nothing {
    if (typeof document === "undefined") {
      return nothing;
    }
    if (!this._roomCard || this._roomCardId !== roomId) {
      const card = document.createElement("danfoss-ally-room-card") as EmbeddedRoomCard;
      card.setConfig({ room_id: roomId });
      this._roomCard = card;
      this._roomCardId = roomId;
    }
    this._roomCard.hass = this.hass;
    return this._roomCard;
  }

  /** Zones qui contiennent des climates d'autres intégrations (lecture seule). */
  private _renderOtherAreas(): TemplateResult {
    const areas = this.hass ? areasWithClimates(this.hass, true) : [];
    return html`
      <section class="home other-areas">
        <div class="home-head">
          <h2>${t(this.hass, "panel_other_areas")}</h2>
        </div>
        <div class="room-sub wrap">${t(this.hass, "panel_other_areas_hint")}</div>
        ${areas.length === 0
          ? html`<div class="unavailable">${t(this.hass, "panel_no_other_areas")}</div>`
          : html`<div class="rooms">${areas.map((area) => this._renderArea(area))}</div>`}
      </section>
    `;
  }

  private _renderArea(area: AreaClimates): TemplateResult {
    const sum = areaSummary(this.hass as HassLike, area.entity_ids);
    const line = areaClimateLine(sum);
    const healthy = sum.offline === 0 && sum.low_battery === 0 && sum.window_open === 0;
    return html`
      <div class="room ${healthy ? "ok" : "attn"}">
        <div class="room-top">
          <span class="room-name" title=${area.name}>${area.name}</span>
          <span class="heads-count">${sum.count}×</span>
        </div>
        ${line ? html`<div class="room-climate">${line}</div>` : nothing}
        <div class="flags">
          ${sum.heating
            ? html`<span class="flag hot">${t(this.hass, "area_heating_n", { n: sum.heating })}</span>`
            : nothing}
          ${sum.window_open ? html`<span class="flag warn">${t(this.hass, "room_window")}</span>` : nothing}
          ${sum.offline ? html`<span class="flag warn">${t(this.hass, "room_offline_n", { n: sum.offline })}</span>` : nothing}
          ${sum.low_battery ? html`<span class="flag warn">${t(this.hass, "room_low_battery_n", { n: sum.low_battery })}</span>` : nothing}
          ${healthy ? html`<span class="flag ok">${t(this.hass, "room_ok")}</span>` : nothing}
        </div>
      </div>
    `;
  }

  private _renderRelay(relay: FleetRelay): TemplateResult {
    // An offline relay's on/off is its last known (stale) state: show it as offline, not "On".
    const offline = relay.online === false;
    const on = !offline && relay.on === true;
    const state = offline ? "offline" : on ? "on" : "off";
    const label = offline ? "relay_offline" : on ? "relay_on" : "relay_off";
    return this._renderChip(
      relay.device_id,
      state,
      relay.name,
      t(this.hass, label),
      offline,
      t(this.hass, "rooms_linked", { n: relay.linked_rooms }),
    );
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
    .bar-actions {
      display: inline-flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .toggle.on {
      background: var(--primary-color, #03a9f4);
      border-color: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, #fff);
    }
    .room-sub.wrap {
      white-space: normal;
      margin: -4px 0 10px;
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
    a.room.link {
      display: block;
      text-decoration: none;
      color: inherit;
      cursor: pointer;
      transition: box-shadow 0.12s ease;
    }
    a.room.link:hover {
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.18);
    }
    a.relay.chip {
      text-decoration: none;
      border: 1px solid var(--divider-color, #e8e8e8);
      border-radius: 14px;
      padding: 3px 10px;
      cursor: pointer;
    }
    a.relay.chip:hover {
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.18);
    }
    .relay-dot.on-ok {
      background: var(--success-color, #2e7d32);
    }
    .section-title {
      margin: 18px 0 6px;
    }
    .ent-list {
      display: flex;
      flex-direction: column;
    }
    .ent-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      width: 100%;
      padding: 9px 4px;
      border: 0;
      border-top: 1px solid var(--divider-color, #eee);
      background: none;
      color: var(--primary-text-color);
      font: inherit;
      font-size: 0.9rem;
      text-align: left;
      cursor: pointer;
    }
    .ent-row:first-child {
      border-top: 0;
    }
    .ent-row:hover {
      background: var(--secondary-background-color, #f5f5f5);
    }
    .ent-state {
      font-variant-numeric: tabular-nums;
      color: var(--secondary-text-color);
      text-align: right;
    }
    .ent-off .ent-state {
      color: var(--warning-color, #ffa600);
      font-style: italic;
    }
    a.room.link:focus-visible,
    a.relay.chip:focus-visible,
    .ent-row:focus-visible,
    .crumb-link:focus-visible {
      outline: 2px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
    }
    .crumbs {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 6px;
      margin: 0 0 12px;
      font-size: 0.9rem;
      color: var(--secondary-text-color);
    }
    .crumb-link {
      color: var(--primary-color, #03a9f4);
      text-decoration: none;
    }
    .crumb-link:hover {
      text-decoration: underline;
    }
    .crumb[aria-current="page"] {
      color: var(--primary-text-color);
      font-weight: 500;
    }
    .room-page h2 {
      margin-bottom: 4px;
    }
    .room-sub.note {
      margin: 10px 0 0;
    }
    .room-card-slot {
      max-width: 520px;
    }
    @media (prefers-reduced-motion: reduce) {
      a.room.link {
        transition: none;
      }
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
    .room.single {
      border-style: dashed;
    }
    .room-sub {
      font-size: 0.72rem;
      color: var(--secondary-text-color);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .room-sub.kind {
      font-style: italic;
    }
    .room-climate {
      font-size: 0.8rem;
      color: var(--primary-text-color);
      font-variant-numeric: tabular-nums;
      margin-top: 2px;
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
    .relay-dot.offline {
      background: transparent;
      border: 2px solid var(--warning-color, #ffa600);
      box-sizing: border-box;
    }
    .relay-offline .relay-state {
      color: var(--warning-color, #ffa600);
      font-weight: 500;
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

/**
 * Préférence locale du bouton « autres zones » (confort par navigateur). Défaut :
 * masquée, car sur une installation où une autre intégration pilote aussi les têtes Ally,
 * la section les montrerait toutes une seconde fois.
 */
const OTHER_AREAS_KEY = "danfoss-ally-panel.show-other-areas";

export function readShowOtherAreas(): boolean {
  try {
    return globalThis.localStorage?.getItem(OTHER_AREAS_KEY) === "1";
  } catch {
    return false;
  }
}

function writeShowOtherAreas(show: boolean): void {
  try {
    globalThis.localStorage?.setItem(OTHER_AREAS_KEY, show ? "1" : "0");
  } catch {
    // Stockage indisponible (navigation privée) : le choix vaut pour la session.
  }
}

/** Maillon du fil d'Ariane ; sans `path`, c'est du texte (maison, niveau courant). */
interface Crumb {
  label: string;
  path?: string;
}

type EmbeddedRoomCard = HTMLElement & {
  hass?: HassLike;
  setConfig(config: RoomCardConfig): void;
};

declare global {
  interface HTMLElementTagNameMap {
    "danfoss-ally-panel": DanfossAllyPanel;
  }
}
