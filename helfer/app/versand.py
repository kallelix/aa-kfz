"""Mails verschicken und Fristen wahren (Lastenheft 2.4, I-03).

Läuft alle MAIL_INTERVALL Sekunden, wenn Mail eingerichtet ist: erst die
fälligen Mails aus mail_out, dann die Fristen – wer seine Anmeldung nicht
bestätigt hat, wird erinnert, und wer es auch danach nicht tut, gibt seine
Plätze frei. Ohne Mail läuft nichts davon: wer keine Mail bekommt, kann
nichts bestätigen, und verfallen darf dann auch nichts.

Fehlschläge wie in Presse: gezählt und mit wachsendem Abstand wiederholt,
nach MAIL_MAX_VERSUCHE bleibt die Mail liegen.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timedelta

import segno

from . import config, db, mail, normalisieren, selbstanmeldung, zugang

protokoll = logging.getLogger("uvicorn.error")


def _backoff(versuche: int) -> str:
    """1, 2, 4, 8 … Minuten, bei einer Stunde gedeckelt."""
    minuten = min(2 ** max(versuche - 1, 0), 60)
    return (db.jetzt_lokal() + timedelta(minutes=minuten)).strftime("%Y-%m-%d %H:%M:%S")


def verschicken() -> tuple[int, int]:
    """Ein Durchgang. Liefert (gesendet, fehlgeschlagen)."""
    gesendet = fehlgeschlagen = 0
    for zeile in db.mails_faellig():
        try:
            mail.senden(zeile["empfaenger"], zeile["betreff"], zeile["body"],
                        _qr_anhang(zeile["qr"]))
        except Exception as ausnahme:  # noqa: BLE001 – jeder Fehler ist ein Fehlversuch
            versuche = zeile["versuche"] + 1
            aufgegeben = versuche >= config.MAIL_MAX_VERSUCHE
            db.mail_fehlgeschlagen(zeile["id"], f"{type(ausnahme).__name__}: {ausnahme}",
                                   None if aufgegeben else _backoff(versuche))
            fehlgeschlagen += 1
            (protokoll.error if aufgegeben else protokoll.warning)(
                "Mail %s (%s) fehlgeschlagen, Versuch %s: %s",
                zeile["id"], zeile["typ"], versuche, ausnahme)
        else:
            db.mail_gesendet(zeile["id"])
            gesendet += 1
    return gesendet, fehlgeschlagen


def _qr_anhang(inhalt: str) -> list:
    """Der QR-Code für den Check-in als PNG – groß genug, dass ein Handy ihn
    vom Bildschirm eines anderen Handys liest."""
    if not inhalt:
        return []
    puffer = io.BytesIO()
    segno.make(inhalt, error="m").save(puffer, kind="png", scale=10, border=4)
    return [("check-in-code.png", "image/png", puffer.getvalue())]


def link(pfad: str) -> str:
    """Absolut, für Mails. Ohne BASIS_URL bleibt nur der Pfad – das meldet
    der Start."""
    return config.BASIS_URL + pfad


def _zeitpunkt(marke: str) -> str:
    """'Sa 03.07. 10:00 Uhr' – für Fristen in Mails."""
    try:
        zeit = datetime.fromisoformat(marke)
    except ValueError:
        return marke
    return config.WOCHENTAGE[zeit.weekday()][:2] + zeit.strftime(" %d.%m. %H:%M Uhr")


def angebot_mails(angebote, basis: str) -> None:
    """R-04: wem die Warteliste einen Platz anbietet, der bekommt Bescheid –
    bei Mitangemeldeten die Person, die sie angemeldet hat."""
    for a in angebote:
        person = db.helfer_laden(a["helfer_id"])
        if person is None:
            continue
        anmelder = db.helfer_laden(person["angemeldet_von"]) if person["angemeldet_von"] else person
        if anmelder is None or not anmelder["email"]:
            continue
        db.mail_einreihen(anmelder["id"], mail.angebot(
            anmelder, person["vorname"] or person["name"], a["schicht"]["text"],
            _zeitpunkt(a["bis"]), basis + "/platz/" + zugang.token(zugang.PLATZ, anmelder)))


def absage_mails(abgaben) -> None:
    """S-07: kurzfristige Absagen und solche, nach denen die Schicht unter
    ihrem Minimum ist, gehen sofort an die Bereichsleitung – gibt es keine,
    an die Orga."""
    for abgabe in abgaben:
        if abgabe["angebot"] or not (abgabe["unter_minimum"] or abgabe["kurzfristig"]):
            continue
        empfaenger = [k["email"] for k in db.leitung_empfaenger(abgabe["schicht"]["bereich_id"])]
        if not empfaenger and config.KONTAKT_MAIL:
            empfaenger = [config.KONTAKT_MAIL]
        for adresse in empfaenger:
            db.mail_einreihen(None, mail.leitung_absage(adresse, abgabe))


def eltern_mail(kind, basis: str) -> bool:
    """D-06: die Bitte um Einverständnis an die Eltern, mit den Schichten
    des Kindes. Ist die anmeldende Person selbst als erziehungsberechtigt
    eingetragen – gleiche Adresse –, zählt ihre eigene Bestätigung, und es
    geht keine Mail."""
    if not kind["eltern_email"] or kind["eltern_bestaetigt_am"]:
        return False
    anmelder_id = kind["angemeldet_von"] or kind["id"]
    anmelder = db.helfer_laden(anmelder_id)
    if (anmelder is not None and anmelder["id"] != kind["id"]
            and anmelder["email"].lower() == kind["eltern_email"].lower()):
        return False
    heute = db.jetzt_lokal().date()
    gesendet = False
    for vid in db.teilnahmen([kind["id"]]):
        v = db.VERANSTALTUNGEN.laden(vid)
        if v is None or v["ende"] < heute:
            continue
        ergebnis = db.anmeldung_laden(vid, anmelder_id)
        eintraege = [e for e in ergebnis["personen"] if e["person"]["id"] == kind["id"]]
        db.mail_einreihen(kind["id"], mail.eltern(
            kind, selbstanmeldung.va_text(v), eintraege,
            basis + "/eltern/" + zugang.token(zugang.ELTERN, kind),
            angemeldet_von=anmelder["name"] if anmelder and anmelder["id"] != kind["id"] else ""))
        gesendet = True
    return gesendet


def fristen() -> tuple[int, int]:
    """Erinnern und verfallen lassen (I-03, D-06), abgelaufene Angebote der
    Warteliste weitergeben (R-04), nach der Rückgabe löschen (S-05).
    Liefert (erinnert, verfallen)."""
    erinnert = verfallen = 0
    frist = config.BESTAETIGEN_FRIST_STUNDEN
    angebote = db.angebote_abgelaufen()
    for person in db.unbestaetigt(frist):
        v = db.VERANSTALTUNGEN.laden(person["veranstaltung_id"])
        frei = db.verfallen_lassen(person["id"])
        angebote += db.nachruecken(frei)
        if v is not None:
            # Ohne helfer_id: die Person ist danach meist gelöscht, und mit ihr
            # gingen sonst auch ihre ungesendeten Mails.
            db.mail_einreihen(None, mail.verfallen(
                person, selbstanmeldung.va_text(v),
                link("/" + normalisieren.kurzadresse(v["kurz"]))))
        protokoll.info("Anmeldung %s nicht bestätigt, %d Plätze frei", person["id"], len(frei))
        verfallen += 1
    # D-06: ohne Einverständnis der Eltern gilt die Anmeldung nicht.
    for kind in db.eltern_offen(frist):
        v = db.VERANSTALTUNGEN.laden(kind["veranstaltung_id"])
        frei = db.eltern_verfallen_lassen(kind["id"])
        angebote += db.nachruecken(frei)
        empfaenger = kind if kind["anmelder_id"] == kind["id"] else db.helfer_laden(kind["anmelder_id"])
        if v is not None and empfaenger is not None and empfaenger["email"]:
            db.mail_einreihen(None, mail.eltern_verfallen(
                empfaenger, kind["name"], selbstanmeldung.va_text(v),
                link("/" + normalisieren.kurzadresse(v["kurz"]))))
        verfallen += 1
    for kind in db.eltern_offen(config.BESTAETIGEN_ERINNERN_STUNDEN, nur_unerinnert=True):
        if eltern_mail(kind, config.BASIS_URL):
            erinnert += 1
        db.eltern_erinnert(kind["id"])
    for person in db.unbestaetigt(config.BESTAETIGEN_ERINNERN_STUNDEN, nur_unerinnert=True):
        v = db.VERANSTALTUNGEN.laden(person["veranstaltung_id"])
        if v is None:
            continue
        rest = max(1, frist - config.BESTAETIGEN_ERINNERN_STUNDEN)
        db.mail_einreihen(person["id"], mail.erinnerung(
            person, selbstanmeldung.va_text(v),
            link("/bestaetigen/" + zugang.token(zugang.BESTAETIGEN, person)),
            zugang.code(person), rest))
        db.erinnert(person["id"])
        erinnert += 1
    angebot_mails(angebote, config.BASIS_URL)
    db.nach_rueckgabe_loeschen()
    db.mails_aufraeumen()
    return erinnert, verfallen


def anmeldestart() -> int:
    """C-08: wer Interesse vorgemerkt hat, bekommt eine Mail, sobald die
    Anmeldung offen ist – einmal. Danach ist die Adresse weg."""
    geschrieben = 0
    for zeile in db.interesse_faellig():
        v = db.VERANSTALTUNGEN.laden(zeile["veranstaltung_id"])
        if v is None:
            continue
        db.interesse_benachrichtigen(zeile["id"], mail.anmeldung_offen(
            zeile["email"], zeile["vorname"], selbstanmeldung.va_text(v),
            link("/" + normalisieren.kurzadresse(v["kurz"]))))
        geschrieben += 1
    return geschrieben


def beteiligt(v, empfaenger) -> list[dict]:
    """Die Einträge für die Mail an `empfaenger`: die eigenen und die derer,
    die ohne eigene Adresse mitangemeldet sind. Angebote der Warteliste, die
    noch offen sind, zählen nicht."""
    anmeldung = db.anmeldung_laden(v["id"], empfaenger["id"])
    eintraege = []
    for e in anmeldung["personen"] if anmeldung else []:
        if e["person"]["id"] != empfaenger["id"] and e["person"]["email"]:
            continue
        schichten = [s for s in e["schichten"] if not s["bestaetigen_bis"]]
        if schichten or e["fenster"] or e["person"]["id"] == empfaenger["id"]:
            eintraege.append({**e, "schichten": schichten, "warteliste": []})
    return eintraege


def _wann(erste: str, heute) -> str:
    tage = (datetime.fromisoformat(erste).date() - heute).days
    return {0: "Heute", 1: "Morgen", 2: "Übermorgen"}.get(tage, "Bald")


def erinnern() -> int:
    """C-02: kurz vor der ersten Schicht eine Erinnerung – Treffpunkt,
    Bereichsleitung mit Nummer, Hinweise, Link zu Mein Helferplatz. Je
    Veranstaltung und Person einmal."""
    jetzt = db.jetzt_lokal()
    erinnert = 0
    for zeile in db.erinnerung_faellig(
            db.marke(jetzt), db.marke(jetzt + timedelta(hours=config.ERINNERN_STUNDEN))):
        v = db.VERANSTALTUNGEN.laden(zeile["vid"])
        person = db.helfer_laden(zeile["empfaenger"])
        if v is None or person is None:
            continue
        eintraege = beteiligt(v, person)
        schichten = [s for e in eintraege for s in e["schichten"]]
        leitungen = db.leitungen(sorted({s["bereich_id"] for s in schichten}))
        leitung, hinweise = [], []
        for s in sorted(schichten, key=lambda s: s["beginn"]):
            for k in leitungen.get(s["bereich_id"], []):
                text = f"{s['bereich']}: {k['name']}" + (f", {k['telefon']}" if k["telefon"] else "")
                if text not in leitung:
                    leitung.append(text)
            if s["hinweis"] and f"{s['bereich']}: {s['hinweis']}" not in hinweise:
                hinweise.append(f"{s['bereich']}: {s['hinweis']}")
        platz = link("/platz/" + zugang.token(zugang.PLATZ, person))
        # T-01: mit Check-in reist der Code als Bild mit.
        checkin = bool(db.angebot(v["id"])["checkin"])
        db.erinnerung_vermerken(v["id"], person["id"], "vorher", mail.vorher(
            person, selbstanmeldung.va_text(v), _wann(zeile["erste"], jetzt.date()),
            eintraege, leitung, hinweise, platz, checkin),
            qr=zugang.token(zugang.CHECKIN, person) if checkin else "")
        erinnert += 1
    return erinnert


def runde() -> None:
    gesendet, fehlgeschlagen = verschicken()
    if anmeldestart():
        protokoll.info("Anmeldestart: Vorgemerkte benachrichtigt")
    if erinnern():
        protokoll.info("Erinnerungen vor der Schicht eingereiht")
    erinnert, verfallen = fristen()
    if gesendet or fehlgeschlagen or erinnert or verfallen:
        protokoll.info("Versand: %s gesendet, %s fehlgeschlagen, %s erinnert, %s verfallen",
                       gesendet, fehlgeschlagen, erinnert, verfallen)


async def schleife(stop: asyncio.Event) -> None:
    """Läuft, bis `stop` gesetzt wird. Versand und Datenbank blockieren und
    wandern deshalb in einen Thread – sonst steht der Webserver still."""
    protokoll.info("Mail-Versand gestartet (alle %s s)", config.MAIL_INTERVALL)
    while not stop.is_set():
        try:
            await asyncio.to_thread(runde)
        except Exception:  # noqa: BLE001 – die Schleife darf nie sterben
            protokoll.exception("Versand: unerwarteter Fehler")
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.MAIL_INTERVALL)
        except asyncio.TimeoutError:
            pass
    protokoll.info("Mail-Versand beendet")
