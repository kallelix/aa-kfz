#!/bin/sh
# Naechtliche Sicherung der Antragsdatenbank.
#
#   install -o abfahrt -g abfahrt -m 750 backup.sh /opt/abfahrt/deploy/backup.sh
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
DATEI="$ZIEL/antraege-$(date +%F).db"

sqlite3 "$DB" ".backup '$DATEI'"
chmod 600 "$DATEI"

# Kurz gegenpruefen, dass die Kopie lesbar ist – eine kaputte Sicherung faellt
# sonst erst auf, wenn man sie braucht.
sqlite3 "$DATEI" "PRAGMA integrity_check;" | grep -q '^ok$' || {
    echo "Sicherung $DATEI ist unbrauchbar" >&2
    exit 1
}

find "$ZIEL" -name 'antraege-*.db' -mtime "+$TAGE" -delete

echo "Sicherung nach $DATEI"
