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

## Version 0.6 - Search Console Connector

- [x] Tilføj read-only desktop OAuth
- [x] Gem og genbrug lokalt OAuth-token
- [x] Hent alle tilgængelige properties og tilladelsesniveauer
- [x] Match properties med Website Registry
- [x] Gem properties uden dubletter
- [x] Vis forbindelsesstatus på dashboardet
- [x] Hent dagstal for klik, visninger, CTR og placering
- [x] Gem dagstal idempotent for matchede websites
- [x] Sammenlign seneste 7 hele dage med de foregående 7 dage
- [x] Vis synkronisering og de fem største klikfald i terminalen
- [x] Hent 180 dages historik til 7/28/90-periodeanalyse
- [x] Beregn og gem SEO Health-score uden dubletter
- [x] Vis trendfordeling og de fem laveste SEO-scorer
- [ ] Hent søgeords- og sidedimensioner

Succeskriterium: AI Office kan sikkert hente og historisere daglige Search Console-totaler for alle matchede websites, fortsætte efter fejl på en enkelt property og sammenligne udviklingen uden at credentials eller tokens versionsstyres eller logges.

## Sprint 16 - SEO Manager Agent

- [x] Analysér 28-dages SEO Health for aktive websites
- [x] Ignorér udfasede, arkiverede og annullerede websites
- [x] Kræv dokumenteret forværring før et recovery-projekt
- [x] Gem SEO-analyser og anbefalinger uden dubletter
- [x] Opret eller opdatér ét SEO Recovery-projekt pr. website
- [x] Opret seks faste delprojekter og fem afhængige startopgaver
- [x] Begræns konkrete opgaver til højst 120 minutter
- [x] Send event ved oprettelse af et nyt recovery-projekt
- [x] Vis SEO Manager-resultater på dashboard og i terminal
- [ ] Udfør websiteændringer gennem godkendte specialist-workflows

Succeskriterium: SEO Manager omsætter kun dokumenterede SEO-problemer til målbare recovery-planer uden selv at ændre websites eller sende Telegram-beskeder.

## Sprint 17 - Web Dashboard v1

- [x] Tilføj lokalt Streamlit-indgangspunkt og mørkt tema
- [x] Vis databasebaseret systemstatus
- [x] Vis website-, projekt-, opgave- og økonomikort
- [x] Tilføj klikbart SEO Health-filter
- [x] Vis fem vigtigste opgaver og aktive SEO Recovery-projekter
- [x] Vis fem seneste salg og Orchestrator-hændelser
- [x] Tilføj sidebar og placeholdersider
- [x] Hold UI-laget SQL-frit og uden eksterne servicekald
- [x] Håndtér tomme og manglende sektionsdata
- [ ] Udbyg placeholdersiderne med read-only detaljevisninger

Succeskriterium: CEO kan starte et mørkt, responsivt dashboard lokalt og se de vigtigste databasebaserede drifts-, økonomi- og SEO-data uden at udløse eksterne handlinger.

## Sprint 18 - Website Intelligence Agent

- [x] Opret samlet profil pr. website
- [x] Sammenkobl Search Console, Partner Ads og SEO Health
- [x] Sammenkobl aktive projekter og opgaver
- [x] Beregn website health og stærke/svage områder
- [x] Registrér CMS, tema, monetization, niche og kategorier
- [x] Gem daglige statistikker og ændringshistorik uden dubletter
- [x] Gem deterministiske website-anbefalinger
- [x] Tilføj read-only Website Profile-side i Streamlit
- [ ] Berig ukendt CMS og tema gennem et særskilt godkendt crawl-workflow

Succeskriterium: AI Office kan vise en samlet, historisk websiteprofil alene ud fra gemte data uden eksterne kald fra agenten eller dashboardet.

## Senere kandidater

- Plausible Analytics
- budget og simpelt regnskab
- Opportunity Score og prioriterede arbejdsordrer
- SEO Manager
- Content Manager
- Webmaster
- Adtraction

Kandidater optages først i en version, når forventet værdi og målemetode er defineret.
