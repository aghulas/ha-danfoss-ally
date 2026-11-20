import { describe, expect, it } from "vitest";

import {
  allyRoomsInArea,
  areaClimateLine,
  areaSummary,
  areasWithClimates,
  canAdjustClimate,
  climateView,
  climatesInArea,
  entityArea,
  headExtras,
  steppedClimateTarget,
} from "../src/area";
import type { Room } from "../src/types";
import { addEntity, building, emptyRegistries, hassWith, z2mClimate } from "./area-fixture";

const room = (id: string, climate: string | null): Room => ({
  id,
  name: `Salle ${id}`,
  product_id: "synthetic00",
  heads: [],
  comfort: 21,
  setback: 16,
  climate_entity_id: climate,
});

describe("zones et climates", () => {
  it("prend la zone de l'entité, sinon celle de son appareil", () => {
    const reg = building();
    reg.entities["climate.bureau_tete"].area_id = "salon";
    const hass = hassWith(reg);
    expect(entityArea(hass, "climate.bureau_tete")).toBe("salon");
    expect(entityArea(hass, "climate.salon_fenetre")).toBe("salon");
    expect(entityArea(hass, "climate.absent")).toBeNull();
  });

  it("liste les climates d'une zone, toutes intégrations, sans les masqués", () => {
    const reg = building();
    z2mClimate(reg, "climate.bureau_cachee", "dev-z3");
    reg.entities["climate.bureau_cachee"].hidden = true;
    const hass = hassWith(reg);
    expect(climatesInArea(hass, "bureau")).toEqual(["climate.bureau", "climate.bureau_tete"]);
    expect(climatesInArea(hass, "cave")).toEqual([]);
  });

  it("liste les zones à climates ; `foreignOnly` écarte ceux de l'intégration", () => {
    const hass = hassWith(building());
    expect(areasWithClimates(hass).map((a) => [a.area_id, a.entity_ids.length])).toEqual([
      ["bureau", 2],
      ["salon", 2],
    ]);
    expect(areasWithClimates(hass, true).find((a) => a.area_id === "bureau")?.entity_ids).toEqual([
      "climate.bureau_tete",
    ]);
  });

  it("une zone supprimée du registre n'est pas listée", () => {
    const reg = building();
    delete reg.areas.salon;
    expect(areasWithClimates(hassWith(reg)).map((a) => a.area_id)).toEqual(["bureau"]);
  });

  it("retrouve la pièce Ally d'une zone par son thermostat de pièce", () => {
    const hass = hassWith(building());
    const rooms = [room("13000000", "climate.bureau"), room("13000001", null)];
    expect(allyRoomsInArea(hass, rooms, "bureau").map((r) => r.id)).toEqual(["13000000"]);
    expect(allyRoomsInArea(hass, rooms, "salon")).toEqual([]);
  });
});

describe("entités d'une tête, appariées par appareil", () => {
  it("lit batterie, vanne, fenêtre, demande de chauffe et lien (noms Zigbee2MQTT)", () => {
    const x = headExtras(hassWith(building()), "climate.salon_fenetre");
    expect(x).toEqual({
      battery: 8,
      low_battery: true,
      valve_opening: 42,
      window_open: true,
      heat_required: true,
      linkquality: 120,
    });
  });

  it("ne prend rien d'un autre appareil, et rien d'indisponible", () => {
    const reg = building();
    reg.states["sensor.salon_fenetre_battery"].state = "unavailable";
    const hass = hassWith(reg);
    expect(headExtras(hass, "climate.salon_fenetre").battery).toBeNull();
    expect(headExtras(hass, "climate.bureau_tete")).toEqual({
      battery: null,
      low_battery: false,
      valve_opening: null,
      window_open: null,
      heat_required: null,
      linkquality: null,
    });
  });

  it("préfère le device_class à la clé, et reconnaît les noms de cette intégration", () => {
    const reg = emptyRegistries();
    z2mClimate(reg, "climate.t", "dev");
    addEntity(reg, "sensor.t_battery", "90", {}, { device_id: "dev" });
    addEntity(reg, "sensor.t_pile", "55", { device_class: "battery" }, { device_id: "dev" });
    addEntity(reg, "sensor.t_ouverture", "30", {}, {
      device_id: "dev",
      translation_key: "valve_opening",
    });
    addEntity(reg, "binary_sensor.t_fenetre", "off", { device_class: "window" }, { device_id: "dev" });
    const x = headExtras(hassWith(reg), "climate.t");
    expect(x.battery).toBe(55);
    expect(x.valve_opening).toBe(30);
    expect(x.window_open).toBe(false);
  });

  it("une fenêtre externe (interrupteur Zigbee2MQTT) ouverte compte comme ouverte", () => {
    const reg = emptyRegistries();
    z2mClimate(reg, "climate.t", "dev");
    addEntity(reg, "sensor.t_window_open_internal", "closed", {}, { device_id: "dev" });
    addEntity(reg, "switch.t_window_open_external", "on", {}, { device_id: "dev" });
    expect(headExtras(hassWith(reg), "climate.t").window_open).toBe(true);
  });

  it("batterie faible signalée par un binary_sensor battery", () => {
    const reg = emptyRegistries();
    z2mClimate(reg, "climate.t", "dev");
    addEntity(reg, "binary_sensor.t_battery_low", "on", { device_class: "battery" }, { device_id: "dev" });
    const x = headExtras(hassWith(reg), "climate.t");
    expect(x.low_battery).toBe(true);
    expect(x.battery).toBeNull();
  });

  it("mesure de repli : capteur de température de l'appareil (hors diagnostic)", () => {
    const reg = emptyRegistries();
    z2mClimate(reg, "climate.t", "dev", { current_temperature: undefined });
    addEntity(reg, "sensor.t_local_temperature", "18.5", {}, { device_id: "dev" });
    expect(climateView(hassWith(reg), "climate.t")?.current).toBe(18.5);
  });
});

describe("écriture d'un climate hors Ally", () => {
  it("réglable : hors Ally, disponible, consigne unique, pas éteint", () => {
    const hass = hassWith(building());
    expect(canAdjustClimate(climateView(hass, "climate.salon_fenetre")!)).toBe(true);
    expect(canAdjustClimate(climateView(hass, "climate.salon_porte")!)).toBe(false);
    expect(canAdjustClimate(climateView(hass, "climate.bureau")!)).toBe(false);
    const reg = building();
    reg.states["climate.bureau_tete"].state = "off";
    expect(canAdjustClimate(climateView(hassWith(reg), "climate.bureau_tete")!)).toBe(false);
    const reg2 = building();
    reg2.states["climate.bureau_tete"].attributes.supported_features = 0;
    expect(canAdjustClimate(climateView(hassWith(reg2), "climate.bureau_tete")!)).toBe(false);
  });

  it("au pas du climate, dans ses bornes, null en butée", () => {
    const reg = emptyRegistries();
    z2mClimate(reg, "climate.t", "dev", { temperature: 29.8, max_temp: 30, target_temp_step: 0.1 });
    const view = climateView(hassWith(reg), "climate.t")!;
    expect(steppedClimateTarget(view, 1)).toBe(29.9);
    expect(steppedClimateTarget(view, -1)).toBe(29.7);
    expect(steppedClimateTarget({ ...view, target: 30 }, 1)).toBeNull();
    expect(steppedClimateTarget({ ...view, target: 5, min: 5 }, -1)).toBeNull();
    expect(steppedClimateTarget({ ...view, ally: true }, 1)).toBeNull();
  });
});

describe("résumé d'une zone (panneau)", () => {
  it("moyenne des mesures, plage des consignes, comptes", () => {
    const hass = hassWith(building());
    const sum = areaSummary(hass, ["climate.salon_fenetre", "climate.salon_porte"]);
    expect(sum).toEqual({
      count: 2,
      temperature: 19.5,
      setpoint_min: 20,
      setpoint_max: 20,
      heating: 1,
      offline: 1,
      low_battery: 1,
      window_open: 1,
    });
    expect(areaClimateLine(sum)).toBe("19.5 °C → 20 °C");
    expect(
      areaClimateLine({ ...sum, temperature: null, setpoint_min: 19, setpoint_max: 21.5 }),
    ).toBe("– → 19–21.5 °C");
    expect(areaClimateLine({ ...sum, temperature: null, setpoint_min: null })).toBeNull();
  });
});
