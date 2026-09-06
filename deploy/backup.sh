#!/bin/sh
# Naechtliche Sicherung der Datenbank. Wird von allen drei Anwendungen
# benutzt; welche gesichert wird, steht in DB_PATH.
#
# Wichtig: sqlite3 ".backup" statt cp. Die Datenbank laeuft im WAL-Modus, ein
# blosses Kopieren der .db-Datei erwischt die noch nicht eingearbeiteten
# Aenderungen im -wal nicht.

set -eu

# Ohne DB_PATH werden ALLE Datenbanken im Verzeichnis gesichert. Seit die
# drei Anwendungen ein Dienst sind, liegen sie nebeneinander in
# /var/lib/abfahrt - ein Aufruf statt drei Cron-Eintraege.
DB="${DB_PATH:-}"
ZIEL="${BACKUP_DIR:-/var/backups/abfahrt}"
TAGE="${BACKUP_TAGE:-30}"

if [ -z "$DB" ]; then
    VERZEICHNIS="${DB_DIR:-/var/lib/abfahrt}"
    gefunden=0
    for eine in "$VERZEICHNIS"/*.db; do
        [ -f "$eine" ] || continue
        gefunden=1
        DB_PATH="$eine" "$0" "$@" || exit 1
    done
    if [ "$gefunden" = "0" ]; then
        echo "Keine Datenbank in $VERZEICHNIS gefunden" >&2
        exit 1
    fi
    exit 0
fi

if [ ! -f "$DB" ]; then
    echo "Datenbank $DB nicht gefunden" >&2
    exit 1
fi

mkdir -p "$ZIEL"

# Der Dateiname folgt der Datenbank: antraege.db -> antraege-2026-08-25.db,
# helfer.db -> helfer-2026-08-25.db. Vorher hiess JEDE Sicherung "antraege-",
# auch die der Presse-App - drei gleich benannte Dateien, die man im Ernstfall
# auseinanderhalten muss, sind eine schlechte Idee.
NAME="$(basename "$DB" .db)"
DATEI="$ZIEL/$NAME-$(date +%F).db"

sqlite3 "$DB" ".backup '$DATEI'"
chmod 600 "$DATEI"

# Kurz gegenpruefen, dass die Kopie lesbar ist – eine kaputte Sicherung faellt
# sonst erst auf, wenn man sie braucht.
sqlite3 "$DATEI" "PRAGMA integrity_check;" | grep -q '^ok$' || {
    echo "Sicherung $DATEI ist unbrauchbar" >&2
    exit 1
}

find "$ZIEL" -name "$NAME-*.db" -mtime "+$TAGE" -delete

# Sicherungen aus der Zeit vor der Umbenennung mit aufraeumen. Ohne diese
# Zeile lagen sie fuer immer im Verzeichnis, weil das Muster oben sie nicht
# mehr trifft.
[ "$NAME" = "antraege" ] || find "$ZIEL" -name 'antraege-*.db' -mtime "+$TAGE" -delete

echo "Sicherung nach $DATEI"
