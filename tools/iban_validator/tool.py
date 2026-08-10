"""
title: IBAN-Prüfung
description: Prüft IBANs auf formale Gültigkeit (Prüfziffer nach ISO 13616) und formatiert sie zur besseren Lesbarkeit.
version: 1.0.0
"""

import re

# Offizielle IBAN-Längen der gängigsten Länder; unbekannte Ländercodes werden
# nur per Prüfziffer validiert.
_IBAN_LENGTHS = {
    'AT': 20,
    'BE': 16,
    'BG': 22,
    'CH': 21,
    'CZ': 24,
    'DE': 22,
    'DK': 18,
    'EE': 20,
    'ES': 24,
    'FI': 18,
    'FR': 27,
    'GB': 22,
    'HR': 21,
    'HU': 28,
    'IE': 22,
    'IT': 27,
    'LI': 21,
    'LT': 20,
    'LU': 20,
    'LV': 21,
    'NL': 18,
    'NO': 15,
    'PL': 28,
    'PT': 25,
    'RO': 24,
    'SE': 24,
    'SI': 19,
    'SK': 24,
}


def _mod97(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    digits = ''.join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97


class Tools:
    async def validate_iban(self, iban: str) -> str:
        """
        Prüft eine IBAN auf formale Gültigkeit (Länge und Prüfziffer nach ISO 13616). Nutze dieses Werkzeug immer, wenn eine IBAN kontrolliert werden soll — rate niemals selbst.

        :param iban: Die zu prüfende IBAN, mit oder ohne Leerzeichen, z. B. "DE89 3704 0044 0532 0130 00".
        :return: Prüfergebnis mit formatierter IBAN oder eine konkrete Fehlermeldung.
        """
        raw = re.sub(r'\s+', '', (iban or '')).upper()
        if not raw:
            return 'Fehler: Es wurde keine IBAN übergeben.'
        if not re.fullmatch(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}', raw):
            return f'Ungültig: "{iban}" hat kein IBAN-Format (Ländercode, 2 Prüfziffern, danach Buchstaben/Ziffern).'

        country = raw[:2]
        expected_length = _IBAN_LENGTHS.get(country)
        if expected_length is not None and len(raw) != expected_length:
            return f'Ungültig: Eine {country}-IBAN muss {expected_length} Stellen haben, "{raw}" hat {len(raw)}.'

        if _mod97(raw) != 1:
            return f'Ungültig: Die Prüfziffer von "{raw}" stimmt nicht (Prüfsumme nach ISO 13616 fehlgeschlagen).'

        formatted = ' '.join(raw[i : i + 4] for i in range(0, len(raw), 4))
        note = '' if expected_length is not None else f' Hinweis: Für den Ländercode {country} ist keine Referenzlänge hinterlegt; geprüft wurde nur die Prüfziffer.'
        return f'Gültig: {formatted} ist eine formal korrekte IBAN ({country}).{note} Die Prüfung sagt nichts darüber aus, ob das Konto existiert.'


if __name__ == '__main__':
    import asyncio

    tools = Tools()

    def check(value):
        return asyncio.run(tools.validate_iban(value))

    assert check('DE89 3704 0044 0532 0130 00').startswith('Gültig')
    assert check('DE89370400440532013000').startswith('Gültig')
    assert check('DE89370400440532013001').startswith('Ungültig')
    assert check('DE89 3704').startswith('Ungültig')
    assert check('XX12ABCDE1234567').startswith('Ungültig') or 'keine Referenzlänge' in check('XX12ABCDE1234567')
    assert check('').startswith('Fehler')
    print('ok')
