"""Helpers Python partagés entre modules de stratégie (indicateurs
techniques déterministes, etc.) — PAS un module de stratégie lui-même.

Le préfixe `_` est volontaire : `shared.strategy_registry.load_definitions_from_directory`
ignore explicitement tout fichier/dossier de `strategies/` commençant par
`_` ou `.` (voir son docstring) — sans ce préfixe, le loader tenterait de
charger ce dossier comme un module de stratégie et échouerait proprement
mais bruyamment (`attribut de module DEFINITION manquant`, consigné comme
un "plugin invalide" à chaque démarrage, alors que ce n'en est pas un)."""
