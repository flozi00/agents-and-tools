# Herkunft übernommener Werkzeuge

Dieser Katalog enthält Werkzeuge, die aus fremden Open-Source-Projekten
übernommen wurden. Der Code ist gegenüber dem Original **unverändert**;
ergänzt wurden ausschließlich der Herkunftshinweis und die Katalog-Metadaten
im Dateikopf. Jede `tool.py` trägt den vollständigen Lizenztext und den
Copyright-Vermerk des Originals mit sich, damit die Angabe auch bei einer
installierten Kopie erhalten bleibt.

## KommI – Kommunale Intelligenz (openCode)

Adapter-Katalog der Initiative *KommI – Kommunale Intelligenz*, veröffentlicht
auf openCode, der Open-Source-Plattform der öffentlichen Verwaltung:
<https://gitlab.opencode.de/kommi/adapter>

| Werkzeug (Hub-ID) | Quelldatei | Quellprojekt | Rechteinhaber | Lizenz |
| --- | --- | --- | --- | --- |
| `gitlab_repo` | `gitlab_adapter.py` | [gitlab-adapter](https://gitlab.opencode.de/kommi/adapter/gitlab-adapter) | Boris van Benthem | MIT No Attribution (MIT-0) |
| `gitlab_ci` | `gitlab_ci_pipeline_adapter.py` | [gitlab-adapter](https://gitlab.opencode.de/kommi/adapter/gitlab-adapter) | Boris van Benthem | MIT No Attribution (MIT-0) |
| `table_analysis` | `table_analysis.py` | [tabellen-analyse](https://gitlab.opencode.de/kommi/adapter/tabellen-analyse) | Boris van Benthem | MIT No Attribution (MIT-0) |
| `openstreetmap` | `osm-adapter.py` | [osm-adapter](https://gitlab.opencode.de/kommi/adapter/osm-adapter) | Boris van Benthem (Stadt Oberhausen) | MIT |
| `niotix_sensors` | `niotix-adapter.py` | [niotix-adapter](https://gitlab.opencode.de/kommi/adapter/niotix-adapter) | Boris van Benthem | MIT |

`osm-adapter` und `niotix-adapter` enthalten keine LICENSE-Datei; die Lizenz
ist im Kopf der jeweiligen Quelldatei als `license: MIT` deklariert. Als
Rechteinhaber gilt der dort genannte Autor.

`gitlab_repo`, `gitlab_ci` und `table_analysis` tragen im Originalkopf
`author: OpenAI` — diese Angabe stammt aus der Quelldatei und wurde
unverändert übernommen. Rechteinhaber laut LICENSE des Quellprojekts ist
Boris van Benthem.

## Regeln für weitere Übernahmen

1. Es wird nur Code übernommen, für den eine **ausdrückliche Lizenz** vorliegt
   — als LICENSE-Datei im Quellprojekt oder als `license:`-Angabe im Kopf der
   Quelldatei. Fehlt beides, gilt das volle Urheberrecht des Autors; eine
   Weiterverbreitung ist dann nicht zulässig, auch nicht bei öffentlich
   einsehbarem Quellcode.
2. Der Herkunftsblock in der `tool.py` nennt Projekt, Quell-URL, Dateiname,
   Autor und Lizenz und enthält den vollständigen Lizenztext.
3. Der Code selbst bleibt unverändert. Notwendige Anpassungen werden im
   Herkunftsblock als Änderung ausgewiesen.
4. Diese Datei wird um eine Zeile pro übernommenem Werkzeug ergänzt.
