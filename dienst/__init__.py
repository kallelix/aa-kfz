"""Der zusammengesetzte Dienst: drei Anwendungen, ein Prozess.

    python -m dienst

Verteilt wird nach Hostname:

    kennzeichen.example.de   ->  Kennzeichen-Antraege, oeffentlich
    presse.example.de        ->  Presse-Akkreditierung, oeffentlich
    helfer.example.de        ->  Monitor und Unterschriften-Tablet
    admin.example.de         ->  alle drei Backoffices unter einer Adresse

Warum nach Hostname und nicht nach Pfad: die oeffentlichen Adressen stehen auf
Plakaten, in Mails und in QR-Codes. Sie muessen bleiben, wie sie sind. Nach
Pfad zu verteilen haette jede davon geaendert.

Das Backoffice liegt umgekehrt unter EINER Adresse, weil dieselben paar Leute
alle drei betreuen. Die Bereiche unterscheiden sich dort am ersten Pfadstueck:
/kennzeichen, /presse, /helfer.
"""
