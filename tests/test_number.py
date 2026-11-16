"""Plateforme number : stub v1.0 (aucune entité pour l'instant)."""

from custom_components.danfoss_ally_cloud import number


async def test_number_setup_vide():
    ajoutees = []
    await number.async_setup_entry(None, None, ajoutees.append)
    assert ajoutees == [[]]  # une seule fournée, vide
