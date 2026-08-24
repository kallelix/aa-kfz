#!/bin/sh
# Naechtliche Sicherung der Datenbank. Wird von allen drei Anwendungen
# benutzt; welche gesichert wird, steht in DB_PATH.
#
# Wichtig: sqlite3 ".backup" statt cp. Die Datenbank laeuft im WAL-Modus, ein
# blosses Kopieren der .db-Datei erwischt die noch nicht eingearbeiteten
# Aenderungen im -wal nicht.

set -eu

DB="${DB_PATH:-/var/lib/abfahrt/antraege.db}"
ZIEL="${BACKUP_DIR:-/var/backups/abfahrt}"
TAGE="${BACKUP_TAGE:-30}"

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
