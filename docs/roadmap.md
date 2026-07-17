# Roadmap

Roadmapet prioriterer den mindste løsning, der kan skabe målbar værdi. Der arbejdes ét kontrolleret trin ad gangen.

## Version 0.1 - Salgsnotifikation

Mål: Send en Telegram-notifikation ved hvert nyt Partner-ads-salg.

- [ ] Dokumentér felterne i Partner-ads-feedet
- [ ] Opret sikker lokal konfiguration
- [ ] Byg og test Notification Service
- [ ] Byg Partner-ads-integrationen
- [ ] Opret lokalt salgslager
- [ ] Identificér nye salg uden dubletter
- [ ] Beregn samlet provision for dagen
- [ ] Formatér salgsnotifikationen
- [ ] Kør kontrollen hvert 30. minut
- [ ] Test genstart, dubletter og fejl
- [ ] Sæt version 0.1 i drift

Succeskriterium: Et nyt salg udløser præcis én korrekt Telegram-besked, og en genstart skaber ikke dubletter.

## Version 0.2 - Historik og drift

- [ ] Oversigt over salg og provision
- [ ] Driftsstatus og fejlalarmer
- [ ] Daglig opsummering
- [ ] Dokumenteret backup og gendannelse

## Version 0.3 - Forklaring af udvikling

- [ ] Tilføj Google Search Console efter konkret databehov
- [ ] Sammenhold trafik og provision pr. website
- [ ] Markér fakta og hypoteser separat
- [ ] Opret første målbare arbejdsordre og feedback-loop

## Version 0.4 - Project Manager og Task Engine

- [x] Opret projekter og ordnede delprojekter
- [x] Opret konkrete opgaver på højst 120 minutter
- [x] Tildel en ansvarlig agent
- [x] Håndter status, blokering og afhængigheder
- [x] Vælg næste udførbare opgave
- [x] Opret første redesignprojekt for Robotland.dk
- [ ] Knyt afsluttede opgaver til effektmålinger

Succeskriterium: Project Manager kan omsætte et projekt til små, afhængige opgaver og altid pege på den næste opgave, der reelt kan udføres.

## Version 0.5 - Agent Orchestrator

- [x] Definér en ensartet hændelsesmodel
- [x] Definér en ensartet handlingsmodel
- [x] Registrér agenter og kapabiliteter
- [x] Route hændelser i en fast, deterministisk rækkefølge
- [x] Gem hændelser, handlinger, afhængigheder og resultater
- [x] Vis køstatus på dashboardet
- [ ] Tilføj sikre workers, som udfører de ventende handlinger

Succeskriterium: En hændelse kan fordeles til en eller flere agenter uden direkte afhængigheder mellem specialagenterne, og rækkefølgen kan genoptages fra databasen.

## Senere kandidater

- Plausible Analytics
- budget og simpelt regnskab
- Opportunity Score og prioriterede arbejdsordrer
- SEO Manager
- Content Manager
- Webmaster
- Adtraction

Kandidater optages først i en version, når forventet værdi og målemetode er defineret.
