/**
 * `hass` synthétique avec registres (zones, appareils, entités, états) pour la
 * carte par zone et le panneau. Données inventées : aucun identifiant réel.
 */
import type {
  HassAreaEntry,
  HassDeviceEntry,
  HassEntityEntry,
  HassEntityState,
  HassLike,
} from "../src/types";

export interface Registries {
  states: Record<string, HassEntityState>;
  entities: Record<string, HassEntityEntry>;
  devices: Record<string, HassDeviceEntry>;
  areas: Record<string, HassAreaEntry>;
}

export function emptyRegistries(): Registries {
  return { states: {}, entities: {}, devices: {}, areas: {} };
}

export function addEntity(
  reg: Registries,
  entityId: string,
  state: string,
  attributes: Record<string, unknown> = {},
  entry: Partial<HassEntityEntry> = {},
): void {
  reg.entities[entityId] = { entity_id: entityId, ...entry };
  reg.states[entityId] = { entity_id: entityId, state, attributes };
}

/** Climate façon Zigbee2MQTT (consigne unique, 5–35 °C, pas 0,5). */
export function z2mClimate(
  reg: Registries,
  entityId: string,
  device: string,
  attrs: Record<string, unknown> = {},
  state = "heat",
): void {
  addEntity(
    reg,
    entityId,
    state,
    {
      friendly_name: entityId.split(".")[1],
      current_temperature: 19.5,
      temperature: 20,
      hvac_action: "idle",
      min_temp: 5,
      max_temp: 35,
      target_temp_step: 0.5,
      supported_features: 1,
      ...attrs,
    },
    { platform: "mqtt", device_id: device },
  );
}

/**
 * Bâtiment synthétique :
 * - zone `salon` : deux têtes Zigbee2MQTT (`dev-z1` avec batterie, vanne, fenêtre,
 *   demande de chauffe, lien ; `dev-z2` indisponible) ;
 * - zone `bureau` : le thermostat de pièce Ally `climate.bureau` (pièce 13000000) et
 *   une tête Zigbee2MQTT `dev-z3` ;
 * - zone `cave` : rien de climate.
 */
export function building(): Registries {
  const reg = emptyRegistries();
  reg.areas = {
    salon: { area_id: "salon", name: "Salon" },
    bureau: { area_id: "bureau", name: "Bureau" },
    cave: { area_id: "cave", name: "Cave" },
  };
  reg.devices = {
    "dev-z1": { id: "dev-z1", area_id: "salon" },
    "dev-z2": { id: "dev-z2", area_id: "salon" },
    "dev-z3": { id: "dev-z3", area_id: "bureau" },
    "dev-room": { id: "dev-room", area_id: "bureau" },
  };
  z2mClimate(reg, "climate.salon_fenetre", "dev-z1", { hvac_action: "heating" });
  addEntity(reg, "sensor.salon_fenetre_battery", "8", { device_class: "battery" }, {
    platform: "mqtt",
    device_id: "dev-z1",
    entity_category: "diagnostic",
  });
  addEntity(reg, "sensor.salon_fenetre_pi_heating_demand", "42", {}, {
    platform: "mqtt",
    device_id: "dev-z1",
  });
  addEntity(reg, "sensor.salon_fenetre_window_open_internal", "open", {}, {
    platform: "mqtt",
    device_id: "dev-z1",
  });
  addEntity(reg, "binary_sensor.salon_fenetre_heat_required", "on", {}, {
    platform: "mqtt",
    device_id: "dev-z1",
  });
  addEntity(reg, "sensor.salon_fenetre_linkquality", "120", {}, {
    platform: "mqtt",
    device_id: "dev-z1",
  });
  z2mClimate(reg, "climate.salon_porte", "dev-z2", {}, "unavailable");
  z2mClimate(reg, "climate.bureau_tete", "dev-z3", { temperature: 21, current_temperature: 20 });
  addEntity(
    reg,
    "climate.bureau",
    "heat",
    {
      friendly_name: "Bureau",
      current_temperature: 20.5,
      temperature: 21,
      supported_features: 1,
      min_temp: 5,
      max_temp: 35,
    },
    { platform: "danfoss_ally_cloud", device_id: "dev-room" },
  );
  return reg;
}

export function hassWith(reg: Registries, extra: Partial<HassLike> = {}): HassLike {
  return {
    callWS: (async () => {
      throw new Error("unknown_command");
    }) as HassLike["callWS"],
    ...reg,
    ...extra,
  };
}
