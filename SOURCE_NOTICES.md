# Original source notices

These historical provenance and license blocks were recorded before the Rust ports. Their references to unchanged Python describe that original snapshot. Current native implementations are derivatives; missing source licenses remain missing.

# Herkunft übernommener Werkzeuge

Dieser Katalog enthält Werkzeuge, die aus fremden Projekten übernommen
wurden. Ergänzt wurden dabei der Herkunftshinweis und die Katalog-Metadaten
im Dateikopf; der Code selbst ist unverändert, sofern im Herkunftsblock der
jeweiligen `tool.py` nichts anderes ausgewiesen ist.

Jede übernommene `tool.py` trägt Projekt, Quell-URL, Urheber und Lizenz im
Kopf mit sich — bei lizenzierten Werkzeugen samt vollständigem Lizenztext,
bei Werkzeugen ohne Lizenzangabe mit einem ausdrücklichen Hinweis darauf.
So bleibt die Angabe auch in einer installierten Kopie erhalten.

## KommI – Kommunale Intelligenz (openCode)

Adapter-Katalog der Initiative _KommI – Kommunale Intelligenz_, veröffentlicht
auf openCode, der Open-Source-Plattform der öffentlichen Verwaltung:
<https://gitlab.opencode.de/kommi/adapter>

### Mit Lizenzangabe

| Werkzeug (Hub-ID) | Quelldatei                      | Quellprojekt                                                                  | Rechteinhaber                        | Lizenz                     |
| ----------------- | ------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------ | -------------------------- |
| `gitlab_repo`     | `gitlab_adapter.py`             | [gitlab-adapter](https://gitlab.opencode.de/kommi/adapter/gitlab-adapter)     | Boris van Benthem                    | MIT No Attribution (MIT-0) |
| `gitlab_ci`       | `gitlab_ci_pipeline_adapter.py` | [gitlab-adapter](https://gitlab.opencode.de/kommi/adapter/gitlab-adapter)     | Boris van Benthem                    | MIT No Attribution (MIT-0) |
| `table_analysis`  | `table_analysis.py`             | [tabellen-analyse](https://gitlab.opencode.de/kommi/adapter/tabellen-analyse) | Boris van Benthem                    | MIT No Attribution (MIT-0) |
| `openstreetmap`   | `osm-adapter.py`                | [osm-adapter](https://gitlab.opencode.de/kommi/adapter/osm-adapter)           | Boris van Benthem (Stadt Oberhausen) | MIT                        |
| `niotix_sensors`  | `niotix-adapter.py`             | [niotix-adapter](https://gitlab.opencode.de/kommi/adapter/niotix-adapter)     | Boris van Benthem                    | MIT                        |

`osm-adapter` und `niotix-adapter` enthalten keine LICENSE-Datei; die Lizenz
ist im Kopf der jeweiligen Quelldatei als `license: MIT` deklariert. Als
Rechteinhaber gilt der dort genannte Autor.

`gitlab_repo`, `gitlab_ci` und `table_analysis` tragen im Originalkopf
`author: OpenAI` — diese Angabe stammt aus der Quelldatei und wurde
unverändert übernommen. Rechteinhaber laut LICENSE des Quellprojekts ist
Boris van Benthem.

### Ohne Lizenzangabe im Quellprojekt

Die folgenden Quellprojekte erklären **keine Lizenz**: sie enthalten weder
eine LICENSE-Datei noch eine `license:`-Angabe im Dateikopf. Damit liegen
alle Rechte beim jeweiligen Urheber. Die Aufnahme in diesen Katalog erfolgt
auf Grundlage der Veröffentlichung auf openCode, der Open-Source-Plattform
der öffentlichen Verwaltung, und ist **ausdrücklich keine
Lizenzeinräumung**. Wer diese Werkzeuge weiterverwendet, sollte die
Rechtelage mit dem genannten Urheber klären. Auf Wunsch eines Urhebers wird
das betreffende Werkzeug entfernt.

| Werkzeug (Hub-ID)       | Quelldatei                         | Quellprojekt                                                                                        | Urheber                              |
| ----------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `recht_nrw`             | `recht-nrw-adapter.py`             | [recht-nrw-adapter](https://gitlab.opencode.de/kommi/adapter/recht-nrw-adapter)                     | Florian Schade – Hochsauerlandkreis  |
| `bsi_stand_der_technik` | `bsi-stand-der-technik-adapter.py` | [bsi_stand_der_technik_tools](https://gitlab.opencode.de/kommi/adapter/bsi_stand_der_technik_tools) | Florian Schade – Hochsauerlandkreis  |
| `openlegaldata`         | `openlegaldata-adapter.py`         | [openlegaldata](https://gitlab.opencode.de/kommi/adapter/openlegaldata)                             | Florian Schade – Hochsauerlandkreis  |
| `gesetze_im_internet`   | `gesetze_im_internet_tools.py`     | [bundesgesetzadapter](https://gitlab.opencode.de/kommi/adapter/bundesgesetzadapter)                 | Boris van Benthem (KommI)            |
| `d3_documents`          | `d3_document_tools.py`             | [d3-adapter](https://gitlab.opencode.de/kommi/adapter/d3-adapter)                                   | Boris van Benthem (KommI)            |
| `mediawiki`             | `mediawiki-adapter.py`             | [mediawiki-adapter](https://gitlab.opencode.de/kommi/adapter/mediawiki-adapter)                     | Boris van Benthem (Stadt Oberhausen) |
| `allris_vorlagen`       | `allris-vorlagen-tools.py`         | [allris-adapter](https://gitlab.opencode.de/kommi/adapter/allris-adapter)                           | Stadt Oberhausen (Boris van Benthem) |

Bei `gesetze_im_internet` wurde zusätzlich die Kommentarzeile
`# Target: OpenWebUI Tools Function` vor dem Docstring entfernt — der
Frontmatter-Parser der Installation erkennt den Kopf nur, wenn die Datei mit
dem Docstring beginnt. Die Änderung ist im Herkunftsblock der `tool.py`
ausgewiesen. Alle übrigen Dateien sind im Code unverändert.

## Regeln für weitere Übernahmen

1. Die Lizenz des Quellprojekts wird vor der Übernahme geprüft und im
   Herkunftsblock benannt. Fehlt eine Lizenz, wird das **ausdrücklich als
   fehlend** ausgewiesen — sowohl in der `tool.py` als auch hier. Eine
   fehlende Lizenz bedeutet, dass alle Rechte beim Urheber liegen; die
   Aufnahme in den Katalog ersetzt keine Rechteeinräumung.
2. Der Herkunftsblock in der `tool.py` nennt Projekt, Quell-URL, Dateiname,
   Autor und Lizenz und enthält den vollständigen Lizenztext.
3. Der Code selbst bleibt unverändert. Notwendige Anpassungen werden im
   Herkunftsblock als Änderung ausgewiesen.
4. Diese Datei wird um eine Zeile pro übernommenem Werkzeug ergänzt.



## allris_vorlagen

"""
title: ALLRIS Vorlagen Tools
description: Sucht Vorlagen im Ratsinformationssystem ALLRIS, gibt Beschlussvorschlag, Beratungsfolge und Beschlusstexte im Volltext aus und listet die Anlagen samt PDF-Text auf.
author: Stadt Oberhausen (Boris van Benthem)
version: 0.2.1
required_open_webui_version: 0.9.5
requirements: httpx, beautifulsoup4, pydantic, pypdf
license: keine Lizenzangabe im Quellprojekt
original_author: Stadt Oberhausen (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/allris-adapter
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : ALLRIS-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/allris-adapter
  Datei   : allris-vorlagen-tools.py
  Autor   : Stadt Oberhausen (Boris van Benthem)
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.
--------------------------------------------------------------------------

Target: OpenWebUI Tools Function



## bsi_stand_der_technik

"""
title: BSI Stand-der-Technik Adapter
description: Findet passende Anforderungen (Controls) aus der maschinenlesbaren BSI Stand-der-Technik-Bibliothek (OSCAL, GitHub) und liefert zitierfaehige Referenzen. Immer aktuell via ETag/Conditional-GET, ohne lokalen Voll-Spiegel.
author: Florian Schade - Hochsauerlandkreis
version: 1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Florian Schade – Hochsauerlandkreis
source_url: https://gitlab.opencode.de/kommi/adapter/bsi_stand_der_technik_tools

KommI-Adapter: gitlab.opencode.de/kommi/adapter/bsi-stand-der-technik-adapter

Findet passende Anforderungen (Controls) aus der maschinenlesbaren BSI
Stand-der-Technik-Bibliothek (OSCAL) und liefert zitierfaehige Referenzen.
Immer aktuell via Conditional-GET (ETag) gegen raw.githubusercontent.com,
ohne lokalen Voll-Spiegel. Keine externen Abhaengigkeiten ausser pydantic
(von OpenWebUI bereitgestellt).

Quelle: https://github.com/BSI-Bund/Stand-der-Technik-Bibliothek
Viewer: https://bsi-community.github.io/Stand-der-Technik-Viewer/

Vier vom LLM aufrufbare Tools:
- suche_stand_der_technik: kataloguebergreifende Stichwortsuche ueber alle
  Controls; liefert bewertete Treffer mit Anforderungstext und zitierfaehiger
  Referenz (referenz_text + klickbare referenz_url). Entwuerfe/Previews
  (Grundschutz++, TLS) werden nur mit preview=True durchsucht.
- hole_control: Volltext eines konkreten Controls (Anforderung, Guidance,
  Metadaten) zum woertlichen Zitieren, z. B. in einer Ausschreibung.
- pruefe_anforderungen: gleicht eine Liste von Anforderungen (z. B. aus einer
  Ausschreibung, vom Chat-LLM extrahiert) deterministisch gegen die Bibliothek
  ab und liefert je Anforderung Control-Kandidaten + heuristisches Verdikt.
- liste_kataloge: verfuegbare Kataloge mit Kurzbeschreibung und Entwurf-Status.

Freshness-Strategie: Kataloge werden on-demand von raw.githubusercontent.com
geladen und modul-intern per ETag/If-None-Match gecacht. Unveraenderte Dateien
liefern HTTP 304 (kein Re-Download). Nur tatsaechlich abgefragte Kataloge landen
im Speicher - kein lokaler Voll-Spiegel.

Installation in OpenWebUI:
1. Adminbereich -> Tools -> Neues Tool
2. Inhalt dieser Datei einfuegen
3. Valves konfigurieren (i. d. R. Defaults ausreichend)
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : BSI Stand-der-Technik Tools
  Quelle  : https://gitlab.opencode.de/kommi/adapter/bsi_stand_der_technik_tools
  Datei   : bsi-stand-der-technik-adapter.py
  Autor   : Florian Schade – Hochsauerlandkreis
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.
--------------------------------------------------------------------------



## calculator

"""
title: Rechner
description: Exakter Taschenrechner für Grundrechenarten, Potenzen, Prozente und Rundung — ohne Schätzfehler des Sprachmodells.
version: 1.0.0
"""



## d3_documents

"""
title: d.velop d.3 Document Tools
author: OpenWebUI Function Assistant
version: 0.1.1
requirements: httpx,pydantic,pypdf,python-docx,python-pptx
description: Durchsucht das Dokumentenmanagement d.velop d.3, liest Dokumente samt Metadaten und extrahiert Text aus PDF-, Word- und PowerPoint-Anhängen.
license: keine Lizenzangabe im Quellprojekt
original_author: Boris van Benthem (KommI)
source_url: https://gitlab.opencode.de/kommi/adapter/d3-adapter

OpenWebUI Function import type: Tools
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : d.3-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/d3-adapter
  Datei   : d3_document_tools.py
  Autor   : Boris van Benthem (KommI)
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.
--------------------------------------------------------------------------

Target: OpenWebUI Tools Function
Purpose: Provide LLM-callable tools for d.velop d.3 / d.velop documents:
         - searchDocuments: full-text search and return reusable document references
         - summarizeDocument: download a referenced document and summarize it with a configurable LLM
         - getDocument: download a referenced document and return its extracted content



## evergabe

"""
title: e-Vergabe Tenders
description: Search, read, and download public procurement tenders from the e-Vergabe marketplace (evergabe-online.de) — listing, tender announcements, and all attached tender documents. Login-free.
author: primeLine Solutions GmbH
version: 1.2.0
requirements: requests
"""



## gesetze_im_internet

"""
title: Gesetze im Internet
description: Findet und liest Bundesrecht über gesetze-im-internet.de — Gesetze nach Titel oder Kürzel suchen, Volltext einzelner Normen abrufen und die öffentliche Volltextsuche nutzen.
version: 0.1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Boris van Benthem (KommI)
source_url: https://gitlab.opencode.de/kommi/adapter/bundesgesetzadapter

gesetze-im-internet.de Basis-Tools für OpenWebUI.

Dieses Modul stellt drei vom LLM aufrufbare Tools bereit:
- findLaw: Findet Gesetze nach Titel/Kürzel im Gesamtinhaltsverzeichnis (gii-toc.xml) und liefert den law_code (Slug)
- getLaw: Abruf eines Gesetzestextes aus https://www.gesetze-im-internet.de/{kuerzel}/xml.zip
- searchLaw: Suche über die öffentliche gesetze-im-internet.de Volltextsuche

Installation in OpenWebUI:
1. Adminbereich -> Tools -> Neues Tool
2. Inhalt dieser Datei einfügen
3. Valves konfigurieren, insbesondere allowed_law_codes
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; weitere Änderungen sind
unten aufgeführt.

  Projekt : Bundesgesetz-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/bundesgesetzadapter
  Datei   : gesetze_im_internet_tools.py
  Autor   : Boris van Benthem (KommI)
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.

Änderungen gegenüber dem Original:
  - Die Kommentarzeile "# Target: OpenWebUI Tools Function" vor dem
  Docstring wurde entfernt. Der Frontmatter-Parser der Installation
  erkennt den Kopf nur, wenn die Datei mit dem Docstring beginnt.
  - Titel, Beschreibung und Version wurden im Kopf ergänzt; das Original
  enthält keine Katalog-Metadaten.
--------------------------------------------------------------------------



## gitlab_ci

"""
title: GitLab CI Pipeline Results Tool
author: OpenAI
version: 0.1.0
required_open_webui_version: 0.4.0
description: Liest GitLab-CI/CD-Ergebnisse: Pipelines, Jobs, Testberichte und Job-Logs — rein lesend, für die Fehlersuche an fehlgeschlagenen Pipelines.
requirements: requests
license: MIT No Attribution (MIT-0)
original_author: KommI – Kommunale Intelligenz (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/gitlab-adapter

OpenWebUI Tools Function specialized in reading GitLab CI/CD pipeline results,
jobs, test reports, and selected job traces to support debugging workflows.

This adapter is read-only. It never creates, retries, cancels, or modifies
pipelines, jobs, repository content, issues, or merge requests.
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : GitLab-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/gitlab-adapter
  Datei   : gitlab_ci_pipeline_adapter.py
  Autor   : KommI – Kommunale Intelligenz (Boris van Benthem)
  Lizenz  : MIT No Attribution (MIT-0)

LICENSE-Datei des Quellprojekts, wortgleich übernommen.
--------------------------------------------------------------------------
MIT No Attribution

Copyright 2026 Boris van Benthem

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
--------------------------------------------------------------------------



## gitlab_repo

"""
title: GitLab Repository Coding Tool
author: OpenAI
version: 0.3.4
required_open_webui_version: 0.4.0
description: Liest und schreibt GitLab-Repositories über die REST-API — Dateien lesen, Branches und Forks anlegen, Änderungen committen, Merge Requests und Issues verwalten.
requirements: requests
license: MIT No Attribution (MIT-0)
original_author: KommI – Kommunale Intelligenz (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/gitlab-adapter

OpenWebUI Tool for reading repository content from GitLab, writing file changes
back via GitLab's REST API using the commits endpoint, managing open
GitLab tasks/issues, listing branches, and creating project forks.
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : GitLab-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/gitlab-adapter
  Datei   : gitlab_adapter.py
  Autor   : KommI – Kommunale Intelligenz (Boris van Benthem)
  Lizenz  : MIT No Attribution (MIT-0)

LICENSE-Datei des Quellprojekts, wortgleich übernommen.
--------------------------------------------------------------------------
MIT No Attribution

Copyright 2026 Boris van Benthem

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
--------------------------------------------------------------------------



## iban_validator

"""
title: IBAN-Prüfung
description: Prüft IBANs auf formale Gültigkeit (Prüfziffer nach ISO 13616) und formatiert sie zur besseren Lesbarkeit.
version: 1.0.0
"""



## mediawiki

"""
title: MediaWiki Suche
description: Sucht im MediaWiki-Volltext, lädt Inhalte, lädt diese als Dateien hoch, gibt die Quellen an, liefert je Seite die internen Verlinkungen und extrahiert Datei-Anhänge (z. B. PDF) als Text.
author: Boris van Benthem - Stadt Oberhausen
version: 0.4
requirements: requests, pypdf
license: keine Lizenzangabe im Quellprojekt
original_author: Boris van Benthem (Stadt Oberhausen)
source_url: https://gitlab.opencode.de/kommi/adapter/mediawiki-adapter
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : MediaWiki-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/mediawiki-adapter
  Datei   : mediawiki-adapter.py
  Autor   : Boris van Benthem (Stadt Oberhausen)
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.
--------------------------------------------------------------------------

Basis: offizieller KommI-Adapter von Boris van Benthem - Stadt Oberhausen
(gitlab.opencode.de/kommi/adapter/mediawiki-adapter, v0.1).
Erweiterung (v0.2-0.4): Florian Schade - Hochsauerlandkreis.
Erweiterung (v0.2): zusaetzliche Funktion get_wiki_page, die eine Seite
abruft und deren interne Seitenlinks (prop=links), Kategorien und
Abschnitts-Gliederung liefert - fuer die gezielte Weiterrecherche von
einer Uebersichtsseite zu ihren Unterseiten.

Zielsystem wird ausschliesslich ueber die Valve mediawiki_base_url
konfiguriert (kein fest verdrahtetes Wiki im Code).



## ms365_graph_mail_send

"""
title: Microsoft 365 Mail (Graph)
description: Sendet Ergebnisse per Microsoft Graph an die eigene E-Mail-Adresse der angemeldeten Person — optional mit Dateianhängen aus der Agent-VM.
author: primeline
version: 1.0.1
"""



## niotix_sensors

"""
title: Niotix Sensor Data Fetch
author: Boris van Benthem
description: Abfragen über die Niotix X-API: (1) Messwerte via POST /xapi/v1/influxdb/query; (2) Sensorliste via GET /xapi/v1/virtual-devices; (3) gültige State Identifier eines Sensors (SHOW TAG VALUES, ohne Zeitfilter). Zeigt Tabellen & Citations in der WebUI.
version: 0.1.1
requirements: aiohttp
license: MIT
original_author: Boris van Benthem
source_url: https://gitlab.opencode.de/kommi/adapter/niotix-adapter
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : Niotix-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/niotix-adapter
  Datei   : niotix-adapter.py
  Autor   : Boris van Benthem
  Lizenz  : MIT

Im Kopf der Originaldatei als "license: MIT" deklariert. Das Quellprojekt
enthält keine LICENSE-Datei; Rechteinhaber ist der dort genannte Autor.
Der nachfolgende Lizenztext ist die Standardfassung der MIT-Lizenz.
--------------------------------------------------------------------------
MIT License

Copyright (c) Boris van Benthem

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
--------------------------------------------------------------------------



## openlegaldata

"""
title: OpenLegalData Adapter
description: Durchsucht Rechtsprechung und Gesetze ueber die offene OpenLegalData.io-API (Gerichtsentscheidungen im Volltext, Aktenzeichen-Lookup, Gesetzbuecher/Paragraphen) und liefert die Inhalte samt Quellen an das Sprachmodell.
author: Florian Schade - Hochsauerlandkreis
version: 1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Florian Schade – Hochsauerlandkreis
source_url: https://gitlab.opencode.de/kommi/adapter/openlegaldata

KommI-Adapter: gitlab.opencode.de/kommi/adapter/openlegaldata

Nutzt ausschliesslich die oeffentliche, dokumentierte REST-API von
de.openlegaldata.io (Rechtsprechung + Gesetze). Das Zielsystem ist ueber
die Valve base_url konfigurierbar (Default: die oeffentliche OpenLegalData-
Instanz). Keine externen Abhaengigkeiten ausser pydantic (von OpenWebUI
bereitgestellt).

Dieses Modul stellt vier vom LLM aufrufbare Tools bereit:
- searchRechtsprechung: Suche in Gerichtsentscheidungen ueber die
  OpenLegalData-API (de.openlegaldata.io/api/cases/). Liefert je Treffer
  id/slug/Gericht/Aktenzeichen/Datum/Typ; damit kann anschliessend
  getRechtsprechung aufgerufen werden.
- getRechtsprechung: Abruf einer Gerichtsentscheidung (id oder slug aus
  searchRechtsprechung). Liefert Volltext oder erkannte Abschnitte
  (Tenor/Tatbestand/Gruende).
- searchOpenLegalDataGesetz: Client-seitige Titel-/Paragraphensuche
  innerhalb eines Gesetzbuchs (gesetzbuch ist Pflichtfeld). Keine
  uebergreifende Suche ueber alle Gesetze, keine Volltextsuche im
  Normtext (siehe API-Einschraenkung unten).
- getOpenLegalDataGesetz: Abruf eines Gesetzbuchs (Kuerzel/ID). Modi:
  Inhaltsverzeichnis (toc), ausgewaehlte Paragraphen (paragraphs) oder
  Volltext (fulltext).

Datenzugang (Stand 2026-07-03):
- Rechtsprechung-Volltextsuche: GET {base}/cases/search/?text=... (echte
  Elasticsearch-Suche mit snippets; page/page_size)
- Aktenzeichen exakt:            GET {base}/cases/?file_number=<AZ>
- Entscheidung im Detail:        GET {base}/cases/<id>/ (mit content-HTML)
- Courts: GET {base}/courts/?search=... (Namensaufloesung, funktioniert;
  liefert u. a. "code", z. B. "LAGBW")
- Laws:  GET {base}/laws/?book_id=<id> (Buch-Normen), GET {base}/laws/<id>/
- Law Books: GET {base}/law_books/?code=<kuerzel> (exakte Kuerzelaufloesung)

WICHTIGE API-EINSCHRAENKUNGEN (live verifiziert, Stand 2026-07-03) - das
sind Bugs/Eigenheiten der oeffentlichen API, keine Fehler dieses Moduls:
- "search=" auf /cases/, /laws/ und /law_books/ wird IGNORIERT (liefert
  immer die volle, ungefilterte Liste). Fuer Rechtsprechung ist deshalb der
  separate Endpunkt /cases/search/?text=... noetig; fuer Gesetze "code="
  (exakt) auf /law_books/ und "book_id=" auf /laws/.
- Auf /cases/search/ ist der Gericht-Filter "court=" ein Gerichts-CODE
  (z. B. "LAGBW"), keine numerische ID. Funktionierende Filter dort:
  court=<code>, court_jurisdiction=<wert>, decision_type=<wert>.
- Datums-Filter auf /cases/search/ (date_after/date_from/...) werden
  ignoriert -> Datum wird in diesem Modul client-seitig gefiltert.
- /cases/ nutzt page/page_size, /laws/ nutzt limit/offset (uneinheitlich).

Hinweis: OpenLegalData ist ein Community-Projekt ohne amtliche
Qualitaetssicherung. Fuer rechtsverbindliche Zwecke sind die amtlichen
Verkuendungsblaetter bzw. Gerichtsveroeffentlichungen massgeblich (siehe
hinweis-Feld in jeder Tool-Antwort).

Installation in OpenWebUI:
1. Adminbereich -> Tools -> Neues Tool
2. Inhalt dieser Datei einfuegen
3. Valves konfigurieren (i. d. R. Defaults ausreichend)
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : OpenLegalData-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/openlegaldata
  Datei   : openlegaldata-adapter.py
  Autor   : Florian Schade – Hochsauerlandkreis
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.
--------------------------------------------------------------------------



## openstreetmap

"""
title: Open Street Map Agent
author: Boris van Benthem (Stadt Oberhausen)
description: Abfrage für Daten aus Open Street Map und Verarbeitung im Sprachmodell. Findet Koordinaten zu Orten, kann Distanzen zwischen Orten berechnen und herausfinden, Ob Adressen in Stadteilen liegen. Alle erarbeiteten Daten können in einer Karte dargestellt werden.
version: 0.3.1
requirements: requests
license: MIT
original_author: Boris van Benthem (Stadt Oberhausen)
source_url: https://gitlab.opencode.de/kommi/adapter/osm-adapter
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : OSM-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/osm-adapter
  Datei   : osm-adapter.py
  Autor   : Boris van Benthem (Stadt Oberhausen)
  Lizenz  : MIT

Im Kopf der Originaldatei als "license: MIT" deklariert. Das Quellprojekt
enthält keine LICENSE-Datei; Rechteinhaber ist der dort genannte Autor.
Der nachfolgende Lizenztext ist die Standardfassung der MIT-Lizenz.
--------------------------------------------------------------------------
MIT License

Copyright (c) Boris van Benthem (Stadt Oberhausen)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
--------------------------------------------------------------------------



## recht_nrw

"""
title: Recht NRW Adapter
description: Durchsucht das geltende und historische NRW-Landesrecht (Gesetze, Rechtsverordnungen, Verwaltungsvorschriften) ueber recht.nrw.de und ruft Normen als Inhaltsverzeichnis, einzelne Paragraphen oder Volltext ab.
author: Florian Schade - Hochsauerlandkreis
version: 1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Florian Schade – Hochsauerlandkreis
source_url: https://gitlab.opencode.de/kommi/adapter/recht-nrw-adapter

KommI-Adapter: gitlab.opencode.de/kommi/adapter/recht-nrw-adapter

Zugriff auf das NRW-Landesrecht ueber den OpenSearch-Endpunkt und die
Download-Fassungen von recht.nrw.de. Keine externen Abhaengigkeiten ausser
pydantic (von OpenWebUI bereitgestellt).

Dieses Modul stellt zwei vom LLM aufrufbare Tools bereit:
- searchLandesrechtNRW: Suche im geltenden/historischen NRW-Landesrecht ueber den
  OpenSearch-Endpunkt von recht.nrw.de. Wendet die Portal-Filter an
  (Status, Dokumenttyp, Titel) und liefert uuid + url je Treffer.
- getLandesrechtNRW: Abruf einer Norm (uuid oder url aus searchLandesrechtNRW). Modi: Inhalts-
  verzeichnis der Paragraphen (toc), ausgewaehlte Paragraphen (paragraphs)
  oder Volltext (fulltext). Quelle ist die saubere Download-Fassung
  /system/files/.../<id>.htm bzw. als Fallback die Detailseite.

Datenzugang (Stand 06/2026, nach Drupal-10-Relaunch):
- Suche:  POST {base}/search-middleware/opensearch_internet/_search (Query-DSL)
- Volltext: GET der Detailseite recht.nrw.de{url} -> Link auf saubere .htm
- Der OpenSearch-Index enthaelt nur Metadaten, KEINEN Normtext.

Hinweise:
- Konsolidierte Fassungen (SGV./SMBl. NRW) sind laut Portal NICHT amtlich
  (Serviceleistung); amtlich sind nur die GV.NRW-/MBl.NRW-PDFs.
- Normtexte selbst sind amtliche Werke (§ 5 UrhG, gemeinfrei).
- Defensiv: Mindestabstand zwischen Requests + Session-Cookie + Referer.

Installation in OpenWebUI:
1. Adminbereich -> Tools -> Neues Tool
2. Inhalt dieser Datei einfuegen
3. Valves konfigurieren (i. d. R. Defaults ausreichend)
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : Recht-NRW-Adapter
  Quelle  : https://gitlab.opencode.de/kommi/adapter/recht-nrw-adapter
  Datei   : recht-nrw-adapter.py
  Autor   : Florian Schade – Hochsauerlandkreis
  Lizenz  : keine Lizenzangabe im Quellprojekt

Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
entfernt.
--------------------------------------------------------------------------



## table_analysis

"""
title: Tabellenanalyse & Statistik
author: OpenAI
author_url: https://openai.com
git_url: https://gitlab.opencode.de/kommi/adapter/tabellen-analyse
description: Analysiert angehängte Excel-, CSV- und PDF-Dateien in Open WebUI, erstellt Profiling, Pivot-/Zeitraumanalysen und wendet statistische Methoden auf Tabellendaten an.
required_open_webui_version: 0.1.0
requirements: pandas,numpy,scipy,openpyxl,pdfplumber
version: 0.1.0
license: MIT No Attribution (MIT-0)
original_author: KommI – Kommunale Intelligenz (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/tabellen-analyse
"""

--------------------------------------------------------------------------
Herkunft / Provenance

Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
unverändert.

  Projekt : Tabellen-Analyse
  Quelle  : https://gitlab.opencode.de/kommi/adapter/tabellen-analyse
  Datei   : table_analysis.py
  Autor   : KommI – Kommunale Intelligenz (Boris van Benthem)
  Lizenz  : MIT No Attribution (MIT-0)

LICENSE-Datei des Quellprojekts, wortgleich übernommen.
--------------------------------------------------------------------------
MIT No Attribution

Copyright 2026 Boris van Benthem

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
--------------------------------------------------------------------------



## tanss_read

"""
title: TANSS Read-Only API
description: Read-only OpenWebUI tool for TANSS — tickets, companies, employees, supports, search, plus a generic GET/query passthrough covering the whole readable TANSS API.
author: flozi00
version: 0.2.0
requirements: requests
"""



## tanss_write

"""
title: TANSS Write API
description: Write tool for TANSS — create and update tickets, add comments, book time tracking entries (supports), and send ticket mails.
author: flozi00
version: 0.1.0
requirements: requests
"""

