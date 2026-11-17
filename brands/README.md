# Assets de marque — `danfoss_ally_cloud`

Icônes prêtes pour une PR dans [`home-assistant/brands`](https://github.com/home-assistant/brands),
prérequis à l'inclusion HACS / au Marketplace.

## Arborescence (à recopier telle quelle dans la PR brands)

```
custom_integrations/danfoss_ally_cloud/
├── icon.png       256 × 256
└── icon@2x.png    512 × 512
```

L'arborescence ici reproduit celle du dépôt brands : copier le dossier
`custom_integrations/danfoss_ally_cloud/` à la racine de `home-assistant/brands`.

## Conformité aux exigences brands

- PNG carré, fond transparent, détouré (pas de marge superflue).
- `icon.png` 256×256, `icon@2x.png` 512×512 (version hDPI, exactement le double).
- Rendu à 2048 px puis réduit en LANCZOS (bords nets). Script :
  `scratchpad/make_icon.py` (hors dépôt).
- Pas de `logo.png` fourni : l'icône suffit pour une intégration custom. En
  ajouter un (hauteur ≤ 256 / ≤ 512) si l'on veut un logo horizontal.

## ⚠ Marque déposée

Cette icône est une **création originale** (molette de thermostat stylisée) ;
elle **n'imite pas** le logo déposé de Danfoss. `home-assistant/brands` héberge
d'ordinaire le vrai logo du fabricant.

**Décision (2026-11-17)** : le remplacement par le logo Danfoss officiel a été
étudié puis écarté pour l'instant.
- Le Design Center Danfoss (compte connecté) n'expose pas de logo corporate
  « maître » propre — seulement des JPG promotionnels à fond et les SVG des
  sous-marques produit (ECtemp, DEVI…), pas le wordmark Danfoss en vectoriel
  transparent.
- Les agrégateurs tiers (CDNLogo, Brandfetch) ne sont **pas** des sources
  autorisées (non affiliés, réutilisation interdite).
- Le logo Danfoss est un **logotype horizontal**, mal adapté à l'`icon.png`
  carré détouré exigé ici.

On conserve donc l'icône originale : repli **conforme** (carré, transparent,
256/512) et défendable pour une intégration communautaire distincte
(`danfoss_ally_cloud`, séparée de `danfoss_ally`). Pour basculer plus tard sur
le logo officiel : récupérer le master vectoriel depuis un portail de marque
Danfoss **autorisé**, avec les droits d'usage, puis remplacer ces fichiers avant
de soumettre la PR brands.

## Après l'intégration dans brands

Une fois la PR brands fusionnée, retirer `ignore: brands` de
`.github/workflows/validate.yml` (la validation HACS exigera alors la présence
de la marque en amont).
