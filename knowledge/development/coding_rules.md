# Coding Rules

## Python-standard

- Projektet målrettes Python 3.12.
- Brug type hints, små fokuserede funktioner og dokumenterede offentlige klasser.
- Brug standardbiblioteket, når det løser opgaven klart og robust.
- Valider eksterne data og vis tydelige, sikre fejl.
- Tilføj tests i forhold til risiko og forretningskritikalitet.

## Arkitektur

- Hold integration, forretningslogik, dataadgang og visning adskilt.
- Genbrug fælles tjenester, når det reducerer reel vedligeholdelse.
- Undgå tidlig kompleksitet og abstraktioner uden dokumenteret behov.
- AI-agenter bruger fælles engines og må ikke skabe parallelle datalag.
- Bevar eksisterende funktionalitet ved refaktorering.

## Databaseprincipper

- `core/database.py` er den centrale databasegrænse.
- Ingen direkte SQL eller `sqlite3` uden for `Database`-klassen.
- Brug unikke ID'er og constraints til at forhindre dubletter.
- Gem beløb numerisk og datoer i et ensartet format.
- Bevar data gennem automatiske, kontrollerede migrationer.
- Gem aldrig tokens, API-nøgler eller andre hemmeligheder i databasen.

## Drift og sikkerhed

- Hemmeligheder hentes fra miljøvariabler eller et secrets-system.
- Tekniske hændelser logges uden credentials.
- Netværksintegrationer skal have timeout og sikker fejlhåndtering.
- Eksterne handlinger med væsentlig konsekvens kræver nødvendig tilladelse.
