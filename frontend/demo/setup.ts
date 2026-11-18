/**
 * Mise en place de la page de démonstration hors Home Assistant.
 *
 * Fournit un faux objet `hass` et des données d'essai SYNTHÉTIQUES (aucune
 * donnée réelle d'installation : « Salle 1 / 2 », group_id 13000000…). Permet de
 * développer la carte sans instance HA. Démarrage : `npm run demo`.
 */
import "../src/main";
import type { DanfossAllyPanel } from "../src/panel";
import type { DanfossAllyRoomCard } from "../src/room-card";
import type { DanfossAllyScheduleCard } from "../src/schedule-card";
import type { DanfossAllyScheduleCardEditor } from "../src/schedule-card-editor";
import type {
  DayKey,
  FleetOverview,
  HassLike,
  Info,
  Room,
  Schedule,
  TimeRange,
  WriteJob,
} from "../src/types";
import { validateDays } from "../src/validate";

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
    product_id: "03wvrwpv",
    comfort: 21.0,
    setback: 14.0,
    temperature: 20.4,
    setpoint: 21.0,
    mode: "at_home",
    heating: true,
    online: true,
    writable: true,
    climate_entity_id: "climate.salle_1",
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
        battery: 92,
        valve_opening: 45,
        heat_request: true,
        window_open: false,
        window_detection: true,
        child_lock: false,
        faults: [],
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
        battery: 15,
        valve_opening: 30,
        heat_request: true,
        window_open: true,
        window_detection: true,
        child_lock: false,
        faults: [{ code: "E14", bit: 13, label: "low battery" }],
      },
    ],
  },
  {
    id: "13000001",
    name: "Salle 2",
    home: "Maison",
    product_id: "03wvrwpv",
    comfort: 20.5,
    setback: 15.0,
    temperature: 19.8,
    setpoint: 15.0,
    mode: "leaving_home",
    heating: false,
    online: true,
    writable: true,
    climate_entity_id: "climate.salle_2",
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
        battery: 80,
        valve_opening: 0,
        heat_request: false,
        window_open: false,
        window_detection: false,
        child_lock: true,
        faults: [],
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
        battery: null,
        valve_opening: null,
        heat_request: null,
        window_open: null,
        window_detection: null,
        child_lock: null,
        faults: [],
      },
    ],
  },
];

// Vue d'ensemble synthétique (contrat §3.6).
const OVERVIEW: FleetOverview = {
  homes: [
    {
      gid: "home-synth",
      name: "Maison",
      holiday_active: false,
      gateways: [{ device_id: "gw-synth", name: "Passerelle", online: true }],
      rooms: [
        {
          id: "13000000",
          name: "Salle 1",
          head_count: 2,
          offline: 0,
          low_battery: 1,
          heating: true,
          window_open: true,
          inconsistent: 0,
          faults: 1,
        },
        {
          id: "13000001",
          name: "Salle 2",
          head_count: 2,
          offline: 1,
          low_battery: 0,
          heating: false,
          window_open: false,
          inconsistent: 1,
          faults: 0,
        },
      ],
      relays: [
        {
          device_id: "relay-synth",
          name: "Relais chaudière",
          on: true,
          online: true,
          linked_rooms: 1,
        },
      ],
    },
  ],
  totals: {
    homes: 1,
    gateways: 1,
    rooms: 2,
    heads: 4,
    offline: 1,
    low_battery: 1,
    heating: 1,
    faults: 1,
    relays_on: 1,
  },
};

// Programmes d'essai synthétiques (contrat §3.2). Heures HH:MM, jours mon..sun.
const SCHEDULES: Record<string, Schedule> = {
  "13000000": {
    target: { type: "room", id: "13000000" },
    name: "Salle 1",
    comfort: 21.0,
    setback: 14.0,
    days: {
      mon: [{ start: "08:30", end: "12:00" }, { start: "13:30", end: "17:30" }],
      tue: [{ start: "08:30", end: "17:30" }],
      wed: [{ start: "08:30", end: "12:00" }],
      thu: [{ start: "08:30", end: "17:30" }],
      fri: [{ start: "08:30", end: "16:00" }],
      sat: [],
      sun: [],
    },
    max_transitions_per_day: 6,
    source: "cloud",
    read_at: "2026-11-16T15:36:00+01:00",
  },
  "13000001": {
    target: { type: "room", id: "13000001" },
    name: "Salle 2",
    comfort: 20.5,
    setback: 15.0,
    days: {
      mon: [{ start: "07:00", end: "19:00" }],
      tue: [{ start: "07:00", end: "19:00" }],
      wed: [{ start: "07:00", end: "19:00" }],
      thu: [{ start: "07:00", end: "19:00" }],
      fri: [{ start: "07:00", end: "19:00" }],
      sat: [{ start: "09:00", end: "12:00" }],
      sun: [],
    },
    max_transitions_per_day: 6,
    source: "cloud",
    read_at: "2026-11-16T15:36:00+01:00",
  },
};

// is_admin true → la démo montre l'édition (lot 5). Mettre false pour voir la
// carte en lecture seule.
const INFO: Info = { version: "0.1.0", local_enabled: false, is_admin: true };

// Abonnés à `jobs/subscribe` (simulation locale, pas de vrai WebSocket).
const jobListeners: ((job: WriteJob) => void)[] = [];
let jobSeq = 0;

function emit(job: WriteJob): void {
  for (const cb of jobListeners) {
    cb(job);
  }
}

// Simule le cycle d'un lot d'écriture (envoyé → appliqué, tête par tête).
function simulateJob(roomId: string, kind: string): WriteJob {
  jobSeq += 1;
  const heads = (ROOMS.find((r) => r.id === roomId)?.heads ?? []).map((h) => ({
    device_id: h.device_id,
    status: "pending" as const,
    detail: null,
  }));
  const job: WriteJob = {
    job_id: `demo-${jobSeq}`,
    kind,
    target: { type: "room", id: roomId },
    status: "sent",
    created_at: new Date().toISOString(),
    heads: heads.map((h) => ({ ...h })),
  };
  // Après un instant, chaque tête « en ligne » passe à appliqué.
  heads.forEach((h, i) => {
    setTimeout(
      () => {
        const online = ROOMS.find((r) => r.id === roomId)?.heads.find(
          (x) => x.device_id === h.device_id,
        )?.online;
        job.heads[i] = {
          device_id: h.device_id,
          status: online ? "applied" : "unreachable",
          detail: null,
        };
        const allApplied = job.heads.every((x) => x.status === "applied");
        const anyApplied = job.heads.some((x) => x.status === "applied");
        job.status = allApplied ? "applied" : anyApplied ? "partial" : "unverified";
        emit({ ...job, heads: job.heads.map((x) => ({ ...x })) });
      },
      800 * (i + 1),
    );
  });
  return { ...job, heads: job.heads.map((x) => ({ ...x })) };
}

// Pour voir la bannière de rechargement : mettre une version différente de celle
// injectée au build, p. ex. `{ ...INFO, version: "9.9.9" }`.
const fakeHass: HassLike = {
  language: "fr",
  connection: {
    async subscribeMessage<T>(
      cb: (msg: T) => void,
      _sub: Record<string, unknown>,
    ): Promise<() => void> {
      const typed = cb as unknown as (job: WriteJob) => void;
      jobListeners.push(typed);
      return () => {
        const i = jobListeners.indexOf(typed);
        if (i >= 0) {
          jobListeners.splice(i, 1);
        }
      };
    },
  },
  async callService(
    domain: string,
    service: string,
    data?: Record<string, unknown>,
  ): Promise<unknown> {
    await new Promise((r) => setTimeout(r, 120));
    // Simule climate.set_temperature : met à jour la consigne de la pièce ciblée.
    if (domain === "climate" && service === "set_temperature") {
      const entity = String(data?.entity_id ?? "");
      const room = ROOMS.find((r) => r.climate_entity_id === entity);
      if (room) {
        room.setpoint = Number(data?.temperature);
      }
    }
    return undefined;
  },
  async callWS<T>(msg: Record<string, unknown>): Promise<T> {
    // Simule la latence et les commandes du contrat §5.3.
    await new Promise((r) => setTimeout(r, 120));
    if (msg.type === "danfoss_ally_cloud/info") {
      return INFO as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/rooms") {
      return { rooms: ROOMS } as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/overview") {
      return OVERVIEW as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/schedule/get") {
      const target = msg.target as { id?: string } | undefined;
      const schedule = target?.id ? SCHEDULES[target.id] : undefined;
      if (!schedule) {
        throw new Error("pièce inconnue");
      }
      return (
        msg.refresh ? { ...schedule, read_at: new Date().toISOString() } : schedule
      ) as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/schedule/validate") {
      const days = msg.days as Record<string, TimeRange[]>;
      const res = validateDays(days ?? {});
      return {
        valid: res.valid,
        transitions: res.transitions,
        errors: res.errors.map((e) => ({ code: e.code, message: e.code, day: e.day })),
      } as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/schedule/set") {
      const target = msg.target as { id?: string };
      const days = msg.days as Partial<Record<DayKey, TimeRange[]>>;
      const schedule = target.id ? SCHEDULES[target.id] : undefined;
      if (!schedule) {
        throw { code: "unknown_target", message: "pièce inconnue" };
      }
      // Applique les jours envoyés au programme simulé.
      for (const [day, ranges] of Object.entries(days) as [DayKey, TimeRange[]][]) {
        schedule.days[day] = ranges.map((r) => ({ ...r }));
      }
      schedule.read_at = new Date().toISOString();
      return simulateJob(target.id!, "set_schedule") as unknown as T;
    }
    if (msg.type === "danfoss_ally_cloud/schedule/restore") {
      const target = msg.target as { id?: string };
      return simulateJob(target.id!, "restore_schedule") as unknown as T;
    }
    throw new Error(`commande non simulée : ${String(msg.type)}`);
  },
};

const panel = document.createElement("danfoss-ally-panel") as DanfossAllyPanel;
panel.hass = fakeHass;
document.getElementById("panel")?.appendChild(panel);

const roomCard = document.createElement("danfoss-ally-room-card") as DanfossAllyRoomCard;
roomCard.setConfig({ room_id: "13000000" });
roomCard.hass = fakeHass;
document.getElementById("room")?.appendChild(roomCard);

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
