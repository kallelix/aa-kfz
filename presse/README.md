# Presse-Akkreditierung

Schwesteranwendung zur Kennzeichen-App im selben Repository. Eigener Container,
eigene Adresse, eigene Datenbank. Grundlage ist
[../docs/plan-presse-akkreditierung.md](../docs/plan-presse-akkreditierung.md).

## Starten

```bash
cd presse
cp .env.example .env
../.venv/Scripts/python.exe -m app.passwort      # Hash in die .env
../.venv/Scripts/python.exe -m app
```

Die virtuelle Umgebung liegt im Wurzelverzeichnis und deckt beide Anwendungen
ab. Vorgabeport ist 8081, damit beide nebeneinander laufen koennen.

## Was die App macht

Fotografen und Videografen melden sich vorab an. Wer kommerziell verwertet,
waehlt zwischen Akkreditierungsgebuehr und Bilderspende. **Es gibt keine
Genehmigung** – wer sich anmeldet, bekommt ein Badge; abgeholt wird am
Orga-Buero.

- **Formular** mit bedingten Feldern: die Wahl der Gegenleistung erscheint nur
  bei kommerzieller Verwertung, die Bildrechte nur bei Bilderspende. Geloest per
  CSS (`:has()`), nicht per JavaScript – faellt die Unterstuetzung aus, steht
  alles da und die Validierung verwirft, was nicht passt.
- **Zwei Zustimmungen mit Zeitstempel**: Sicherheitshinweis immer, Bildrechte
  bei Bilderspende. Die Texte stehen im Code, nicht in Env-Variablen: bei einer
  Rechtsaussage will man nachvollziehen koennen, welchem Wortlaut jemand
  zugestimmt hat.
- **Abholliste** fuers Orga-Buero mit Suche im Browser, Sortierung per
  Spaltenkopf und Haekchen fuer Badge und Gebuehr.
- **Bilder ausstehend**: wer die Spende gewaehlt und sein Badge abgeholt hat,
  aber noch nicht geliefert hat. Erinnerung einzeln oder als Sammelaktion.
- **CSV-Export** wie in der Kennzeichen-App: UTF-8 mit BOM, Semikolon, ohne
  IP-Spalte, aber mit den Zeitstempeln der Zustimmungen.

## Konfiguration

Siehe [.env.example](.env.example). Erwaehnenswert:

- `GEBUEHR_BETRAG`, `GEBUEHR_WAEHRUNG` – Akkreditierungsgebuehr
- `BILDER_ANZAHL` – Umfang der Bilderspende
- `BILDER_ABGABE` – wohin die Bilder sollen; solange leer, nennt die
  Erinnerungsmail keinen Weg, sondern bittet um eine Antwort auf die Mail
- `BADGES_GESAMT` – Zahl der vorproduzierten Badges. Ist sie erreicht, warnen
  Formular und Backoffice; **abgewiesen wird niemand**, sonst traefe es auch
  den Fotografen, den die Orga eigentlich dabeihaben will.
- `ABHOLORT` – steht im Formular, auf der Bestaetigungsseite und in der Mail

## Tests

```bash
../.venv/Scripts/python.exe tests/test_anmeldung.py   # Formular und Datenmodell
../.venv/Scripts/python.exe tests/test_backoffice.py  # Anmeldung, Liste, Abholliste
../.venv/Scripts/python.exe tests/test_mail.py        # Vorlagen, Bilder ausstehend
../.venv/Scripts/python.exe tests/test_export.py      # CSV
```

Alle vier starten den Server selbst und legen sich eine Wegwerf-Datenbank an.
Es geht nichts nach draussen: ohne `SMTP_HOST` sammeln sich die Mails in der
Warteschlange.

## Deployment

Abschnitt 7 in [../deploy/README.md](../deploy/README.md).
