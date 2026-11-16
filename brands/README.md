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
d'ordinaire le vrai logo du fabricant : si l'on dispose du kit de marque officiel
Danfoss **et** des droits de l'utiliser, remplacer ces fichiers par le logo
officiel avant de soumettre la PR. Sinon, cette icône originale est un repli
acceptable pour une intégration communautaire distincte (`danfoss_ally_cloud`,
séparée de `danfoss_ally`).

## Après l'intégration dans brands

Une fois la PR brands fusionnée, retirer `ignore: brands` de
`.github/workflows/validate.yml` (la validation HACS exigera alors la présence
de la marque en amont).
