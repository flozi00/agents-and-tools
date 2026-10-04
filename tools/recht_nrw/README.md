# Recht NRW Adapter

Der Katalogeintrag verwendet die native Ausführung in EU-Prompts privater
Tool-VM. Die bisherigen Such- und Abruffunktionen, Einstellungen und
Quellenangaben bleiben erhalten. Die Standardadresse ist `recht.nrw.de`.

Die Suche filtert nach Dokumenttyp, Geltungsstatus und optional nur nach Titel.
Ein gefundener Link oder eine UUID kann als Inhaltsverzeichnis, ausgewählte
Paragraphen oder Volltext abgerufen werden. Der Adapter verwendet die
Download-Fassung und fällt bei leerem Download-Text auf die Detailseite zurück.

Portal-Cookies gelten nur für einen Aufruf. Requests und Weiterleitungen
bleiben an Schema, Host und Port der konfigurierten Adresse gebunden; fremde
Links werden vor dem Zugriff abgewiesen. Antwortgrößen und Abstand zwischen
Requests bleiben begrenzt. Ein fehlgeschlagener optionaler Cookie-Bootstrap
verhindert einen ansonsten möglichen Suchzugriff nicht.

Konsolidierte Fassungen sind Serviceleistungen und nicht amtlich. Amtlich sind
die Verkündungsblatt-PDFs. Urheber und ursprüngliche Lizenzangabe stehen in
`metadata.json`. Der vollständige Herkunftshinweis bleibt in
`backend/native/exec-runner/BUNDLED_TOOL_NOTICES.md` erhalten; die native
Umstellung erteilt keine zusätzliche Lizenz für das übernommene Material.
