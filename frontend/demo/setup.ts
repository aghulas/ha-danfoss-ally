/**
 * Mise en place de la page de démonstration hors Home Assistant.
 *
 * Fournit un faux objet `hass` et des données d'essai SYNTHÉTIQUES (aucune
 * donnée réelle d'installation : « Salle 1 / 2 », group_id 13000000…). Permet de
 * développer la carte sans instance HA. Démarrage : `npm run demo`.
 */
import "../src/main";
import type { DanfossAllyScheduleCard } from "../src/schedule-card";
import type { DanfossAllyScheduleCardEditor } from "../src/schedule-card-editor";
import type { HassLike, Info, Room } from "../src/types";

// `ha-card` factice : la démo n'a pas les composants de Home Assistant. Défini
// globalement, il est aussi « upgradé » à l'intérieur du shadow DOM de la carte,
// ce qui donne un rendu proche de celui dans HA.
if (!customElements.get("ha-card")) {
  class HaCard extends HTMLElement {
    connectedCallback(): void {
      const header = this.getAttribute("header") ?? "";
      const root = this.attachShadow({ mode: "open" });
      root.innerHTML = `
        <style>
          :host {
            display: block;
            background: var(--card-background-color, #fff);
            border-radius: var(--ha-card-border-radius, 12px);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
            overflow: hidden;
          }
          .header {
            padding: 16px;
            font-size: 1.3rem;
            font-weight: 400;
            color: var(--primary-text-color, #212121);
          }
        </style>
        ${header ? `<div class="header">${header}</div>` : ""}
        <slot></slot>
      `;
    }
  }
  customElements.define("ha-card", HaCard);
}

// --- Données d'essai synthétiques (contrat §3.3 / §3.4) ---
const ROOMS: Room[] = [
  {
    id: "13000000",
    name: "Salle 1",
    home: "Maison",
    product_id: "synthetic00",
    comfort: 21.0,
    setback: 14.0,
    heads: [
      {
        device_id: "head-synth-1",
        name: "Salle 1 #1",
        room_id: "13000000",
        online: true,
        mode_displayed: "at_home",
        schedule_active: true,
        preheat: false,
        mounting: false,
        inconsistent: false,
      },
      {
        device_id: "head-synth-2",
        name: "Salle 1 #2",
        room_id: "13000000",
        online: true,
        mode_displayed: "at_home",
        schedule_active: true,
        preheat: false,
        mounting: false,
        inconsistent: false,
      },
    ],
  },
  {
    id: "13000001",
    name: "Salle 2",
    home: "Maison",
    product_id: "synthetic00",
    comfort: 20.5,
    setback: 15.0,
    heads: [
      {
        device_id: "head-synth-3",
        name: "Salle 2 #1",
        room_id: "13000001",
        online: true,
        mode_displayed: "manual",
        schedule_active: false,
        preheat: null,
        mounting: false,
        inconsistent: true,
      },
      {
        device_id: "head-synth-4",
        name: "Salle 2 #2",
        room_id: "13000001",
        online: false,
        mode_displayed: "at_home",
        schedule_active: null,
        preheat: null,
        mounting: false,
        inconsistent: false,
      },
    ],
  },
];

const INFO: Info = { version: "0.1.0", local_enabled: false, is_admin: true };

// Pour voir la bannière de rechargement : mettre une version différente de celle
// injectée au build, p. ex. `{ ...INFO, version: "9.9.9" }`.
const fakeHass: HassLike = {
  language: "fr",
  async callWS<T>(msg: Record<string, unknown>): Promise<T> {
    // Simule la latence et les commandes du contrat §5.3.
    await new Promise((r) => setTimeout(r, 120));
    if (msg.type === "danfoss_ally_cloud/info") {
      return INFO as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/rooms") {
      return { rooms: ROOMS } as unknown as T;
    }
    throw new Error(`commande non simulée : ${String(msg.type)}`);
  },
};

const card = document.createElement("danfoss-ally-schedule-card") as DanfossAllyScheduleCard;
card.setConfig({ room_id: "13000000" });
card.hass = fakeHass;
document.getElementById("app")?.appendChild(card);

const editor = document.createElement(
  "danfoss-ally-schedule-card-editor",
) as DanfossAllyScheduleCardEditor;
editor.setConfig({ room_id: "13000000" });
editor.hass = fakeHass;
editor.addEventListener("config-changed", (ev) => {
  const config = (ev as CustomEvent).detail.config;
  card.setConfig(config);
  card.requestUpdate();
});
document.getElementById("editor")?.appendChild(editor);
