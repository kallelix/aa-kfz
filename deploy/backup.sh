#!/bin/sh
# Naechtliche Sicherung der Datenbank: ein pg_dump fuer alle drei Bereiche.
# Kennzeichen, Presse und Helfer liegen in einer Datenbank, jeder in seinem
# Schema - eine Datei sichert also alles.
#
# Laeuft als Benutzer abfahrt (crontab -u abfahrt). Der meldet sich ueber den
# Unix-Socket ohne Passwort an (peer), genau wie der Dienst. Von root
# aufgerufen, wechselt das Skript selbst dorthin.

set -eu
# Die Sicherung enthaelt Personendaten: von Anfang an nur fuer abfahrt lesbar,
# nicht erst nach einem chmod.
umask 077

if [ "$(id -u)" = "0" ]; then
    exec runuser -u abfahrt -- "$0" "$@"
fi

URL="${DATABASE_URL:-postgresql://abfahrt@/abfahrt?host=/var/run/postgresql}"
ZIEL="${BACKUP_DIR:-/var/backups/abfahrt}"
TAGE="${BACKUP_TAGE:-30}"

mkdir -p "$ZIEL"
DATEI="$ZIEL/abfahrt-$(date +%F-%H%M).dump"

# Erst unter einem Zwischennamen: bricht pg_dump ab, liegt keine halbe Datei
# mit dem Namen einer guten im Verzeichnis. Das Custom-Format ist komprimiert
# und laesst sich mit pg_restore auch nur teilweise zurueckspielen, etwa ein
# einzelnes Schema.
pg_dump --format=custom --dbname="$URL" --file="$DATEI.teil"

# Kurz gegenpruefen, dass die Datei lesbar ist - eine kaputte Sicherung faellt
# sonst erst auf, wenn man sie braucht. pg_restore --list liest das ganze
# Inhaltsverzeichnis und scheitert an einer abgeschnittenen Datei.
pg_restore --list "$DATEI.teil" > /dev/null || {
    echo "Sicherung $DATEI.teil ist unbrauchbar" >&2
    exit 1
}
mv "$DATEI.teil" "$DATEI"

find "$ZIEL" -name 'abfahrt-*.dump' -mtime "+$TAGE" -delete

# Die SQLite-Sicherungen aus der Zeit vor dem Umzug laufen genauso aus.
find "$ZIEL" -name '*.db' -mtime "+$TAGE" -delete

echo "Sicherung nach $DATEI"
