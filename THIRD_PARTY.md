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
