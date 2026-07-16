# Udviklingsstandarder

## Produktprincipper

1. Alle mål skal være målbare.
2. En opgave er først afsluttet, når effekten er målt.
3. Ingen anbefaling må gives uden begrundelse og datagrundlag.
4. Fakta, hypoteser, beslutninger og resultater holdes adskilt.
5. AI anvendes kun, hvor fortolkning eller dømmekraft skaber værdi.
6. Entydige kontroller implementeres deterministisk.
7. Første løsning skal være den mindste løsning, der leverer reel værdi.
8. AI Office må ikke skabe mere arbejde eller støj, end det sparer.

## Udviklingsprincipper

- Dokumentér en komponents formål, input, output, ansvar og version.
- Tilføj tests i forhold til risiko og forretningskritikalitet.
- Log fejl uden at afsløre hemmeligheder.
- Gør integrationer robuste over for midlertidige netværks- og datafejl.
- Undgå tidlig kompleksitet og abstraktioner uden et dokumenteret behov.
- Genbrug fælles tjenester, når det reducerer reel vedligeholdelse.
- Bevar data, så systemet kan genstartes uden dobbelte notifikationer.

## Sikkerhed

- Ingen tokens, API-nøgler, adgangskoder, Chat ID'er eller private feedadresser i Git.
- Brug miljøvariabler eller et egnet secrets-system.
- Giv kun integrationer de mindst nødvendige rettigheder.
- Eksterne handlinger med væsentlig konsekvens kræver eksplicit tilladelse.

## Kvalitetskrav til loops

Et loop skal have:

- et klart startpunkt,
- en målbar baseline,
- et ønsket mål,
- en konkret handling,
- en måleperiode,
- en stopregel,
- en regel for eskalering eller ny hypotese,
- en gemt konklusion.
