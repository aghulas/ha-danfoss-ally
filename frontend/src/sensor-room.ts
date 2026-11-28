/**
 * Pièce Danfoss d'un capteur de pièce sur sa page (contrat companion §3, `sensor_room`).
 *
 * Logique pure, sans DOM : quel geste est possible, quelles pièces proposer, et quand une
 * demande est confirmée. L'état affiché est TOUJOURS celui que le pont a relu
 * (`bridge/sensor_rooms` via `overview`), jamais celui demandé.
 */
import type { FleetOverview, FleetSensor, FleetSensorRoom } from "./types";

/** Demande en cours : envoyée au pont, pas encore relue (`room_id` null = retrait). */
export interface SensorRoomPending {
  sensor: string;
  room_id: string | null;
}

/**
 * Geste possible maintenant : `assign` (dans aucune pièce), `remove` (dans une pièce), ou
 * `null` (lecture seule, demande en cours, ou pièce inconnue). `writable` : le pont annonce
 * `sensor_room` pour ce capteur ET l'utilisateur est administrateur.
 */
export function sensorRoomAction(
  sensor: FleetSensor,
  writable: boolean,
  pending: SensorRoomPending | null,
): "assign" | "remove" | null {
  if (!writable || pending !== null || sensor.cloud_room === undefined) {
    return null;
  }
  return sensor.cloud_room === null ? "assign" : "remove";
}

/** Pièces proposées pour y placer le capteur : celles sans autre capteur. */
export function sensorRoomChoices(sensor: FleetSensor): FleetSensorRoom[] {
  return (sensor.cloud_rooms ?? []).filter((room) => room.sensor_id === null);
}

/** Le capteur de cette vue d'ensemble, ou `undefined`. */
export function findSensor(overview: FleetOverview | null, sensorId: string): FleetSensor | undefined {
  for (const home of overview?.homes ?? []) {
    const sensor = (home.sensors ?? []).find((s) => s.device_id === sensorId);
    if (sensor) {
      return sensor;
    }
  }
  return undefined;
}

/** Vrai quand la vue d'ensemble montre le capteur dans la pièce demandée (relue par le pont). */
export function sensorPendingConfirmed(
  overview: FleetOverview | null,
  pending: SensorRoomPending,
): boolean {
  const room = findSensor(overview, pending.sensor)?.cloud_room;
  if (room === undefined) {
    return false;
  }
  return pending.room_id === null ? room === null : room?.room_id === pending.room_id;
}
