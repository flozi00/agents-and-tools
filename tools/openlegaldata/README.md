# OpenLegalData Adapter

Der Katalogeintrag verwendet die native Ausführung in EU-Prompts privater
Tool-VM. Die vier bisherigen Funktionen, Quellenangaben und Einstellungen
bleiben erhalten. Die Standardadresse ist die öffentliche OpenLegalData-API;
ein API-Token ist optional.

Rechtsprechung kann als Volltext, nach Aktenzeichen oder als Datumsliste gesucht
werden. Die Gesetzessuche benötigt ein Gesetzbuch-Kürzel oder eine Buch-ID und
durchsucht Paragraphentitel und Bezeichnungen. Der Abruf liefert ein
Inhaltsverzeichnis, ausgewählte Normen oder den vollständigen Text. Die API
unterstützt keine zuverlässige Volltextsuche über sämtliche Gesetzbücher.

Requests und Weiterleitungen bleiben an die konfigurierte HTTP-Adresse
(Schema, Host und Port) gebunden. Antwortgrößen, Seitenzahl und Abstand zwischen
Requests bleiben begrenzt. Der optionale Token wird nicht an andere Adressen
weitergegeben. Request-Zeitpunkte gelten nur für einen Aufruf.

Die Daten sind nicht amtlich qualitätsgesichert; für rechtsverbindliche Zwecke
sind amtliche Veröffentlichungen maßgeblich. Urheber und ursprüngliche
Lizenzangabe stehen in `metadata.json`. Der vollständige Herkunftshinweis bleibt
in `backend/native/exec-runner/BUNDLED_TOOL_NOTICES.md` erhalten; die native
Umstellung erteilt keine zusätzliche Lizenz für das übernommene Material.
