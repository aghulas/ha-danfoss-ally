import { describe, expect, it } from "vitest";

import { needsReload } from "../src/version";

describe("needsReload", () => {
  it("ne propose rien quand la version serveur est absente (info manquante)", () => {
    // Cas lot 2 non déployé : `danfoss_ally_cloud/info` renvoie null -> pas de bannière.
    expect(needsReload("0.1.0", null)).toBe(false);
    expect(needsReload("0.1.0", undefined)).toBe(false);
    expect(needsReload("0.1.0", "")).toBe(false);
  });

  it("ne propose rien quand les versions coïncident", () => {
    expect(needsReload("0.1.0", "0.1.0")).toBe(false);
  });

  it("propose un rechargement quand les versions diffèrent", () => {
    expect(needsReload("0.1.0", "0.2.0")).toBe(true);
    expect(needsReload("0.2.0", "0.1.0")).toBe(true);
  });
});
