/**
 * Version de la carte, injectée au build depuis le manifest de l'intégration
 * (Vite `define` -> `__CARD_VERSION__`). Repli `0.0.0` hors build (tests, démo
 * ouverte sans `define`).
 */
export const CARD_VERSION: string =
  typeof __CARD_VERSION__ !== "undefined" ? __CARD_VERSION__ : "0.0.0";

/**
 * Faut-il proposer de recharger la page ? (contrat §6)
 *
 * On ne propose que si `info` a bien renvoyé une version ET qu'elle diffère de
 * celle du bundle chargé. Tant que `danfoss_ally_cloud/info` n'existe pas
 * (lot 2 non déployé) la version du serveur est `null` : pas de proposition,
 * dégradation propre.
 */
export function needsReload(
  cardVersion: string,
  serverVersion: string | null | undefined,
): boolean {
  if (!serverVersion) {
    return false;
  }
  return cardVersion !== serverVersion;
}
