# Roadmap

## Sprint 37 – stabilisering

- [x] Permanent Approved Change som autoritativ datakilde
- [x] Rapporterende databaseaudit og eksplicit safe repair
- [x] Idempotent godkendelse og implementering
- [x] Fælles dokumentation af workflowstatusser
- [x] Dansk visning af interne statusværdier
- [x] Browseraudit af dashboardets sider og responsive kernevisninger
- [ ] Erstat den udfasede Streamlit HTML-komponent til kopier-knapper, når en
  kompatibel clipboard-komponent er tilgængelig

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

## Sprint 19 - OpenAI-forbindelse

- [x] Tilføj den officielle OpenAI Python-pakke
- [x] Opret en isoleret `AIService`
- [x] Læs API-nøglen fra `OPENAI_API_KEY`
- [x] Brug Responses API med en fast testinstruktion
- [x] Udskriv kun modellens forventede tekst ved succes
- [x] Sanitér API-fejl til en kort kategori
- [x] Gem kun boolsk forbindelsesstatus
- [x] Vis OpenAI-status i det read-only dashboard
- [x] Test manglende nøgle, succes, hemmeligheder og fast payload
- [ ] Send forretningsdata til OpenAI gennem særskilt godkendte workflows

Succeskriterium: AI Office kan verificere OpenAI-forbindelsen uden at eksponere nøglen eller sende virksomhedsdata, mens dashboardet fortsat kun læser lokal databasestatus.

## Sprint 20 - AI Analyst Agent

- [x] Analysér website, projekt og opgave
- [x] Byg prompt fra gemte driftsdata og godkendt Knowledge Engine-viden
- [x] Fjern credentials, secrets og personoplysninger før API-kald
- [x] Kræv og validér det definerede JSON-schema
- [x] Forsøg automatisk én gang mere ved ugyldig JSON
- [x] Gem to ugyldige svar som saniteret fejlrapport
- [x] Gem model, tokenforbrug og svartid
- [x] Klassificér confidence uden at udføre handlinger
- [x] Vis AI Status på forsiden
- [x] Tilføj read-only AI Analyst-side med fuld rapport
- [x] Test JSON, retry, database, dashboard og databeskyttelse
- [ ] Planlæg automatisk daily analysis gennem et godkendt scheduler-workflow

Succeskriterium: AI Analyst kan omsætte gemte data og virksomhedsregler til validerede, begrundede anbefalinger uden selv at ændre websites, projekter eller opgaver.

## Sprint 21 - AI Executive

- [x] Saml tværgående virksomhedskontekst uden credentials
- [x] Ignorér udfasede, arkiverede og annullerede websites
- [x] Rangér muligheder 0-100 ud fra konkret evidens
- [x] Returnér og gem højst tre validerede fokusområder
- [x] Begræns næste opgave til højst 120 minutter
- [x] Genbrug aktive projekter i anbefalingen
- [x] Tilføj Executive Briefing-dashboard og forsigtig tom tilstand
- [x] Undgå automatiske projekter, opgaver, websiteændringer og beskeder

Succeskriterium: AI Executive kan udpege højst tre forklarlige,
godkendelseskrævende fokusområder uden operationelle sideeffekter.

## Sprint 22 - Website Discovery

- [x] Scan faste offentlige website-endpoints med timeout og User-Agent
- [x] Dokumentér CMS, tema og page builder uden gæt
- [x] Registrér robots, sitemap, HTTPS, metadata og schema
- [x] Begræns sitemapoptælling til 10.000 URL'er
- [x] Gem current profil og change-only historik
- [x] Isolér websitefejl og sanitér fejltypen
- [x] Opret issue-events uden projekter eller opgaver
- [x] Tilføj brugerstartet Website Discovery-dashboard

Succeskriterium: aktive websites kan få en faktabaseret teknisk profil uden
login, remote writes eller lagring af følsomt/råt indhold.

## Sprint 23 - Website Connector Framework

- [x] Definér et generelt read-only BaseConnector-interface
- [x] Implementér WordPress REST med offentlig HTML-fallback
- [x] Vælg connector fra dokumenteret Website Discovery-CMS
- [x] Normalisér indlæg, sider, taksonomier og medier
- [x] Gem content idempotent ved hjælp af hash
- [x] Opret event efter mere end 20 ændrede sider
- [x] Tilføj søgning, filtrering, sortering og detaljer i Content Explorer
- [x] Undgå login, credentials, cookies, tokens og remote writes

Succeskriterium: AI Office kan læse og udforske offentligt WordPress-indhold
uden at ændre websites eller genimportere uændrede elementer.

## Sprint 24 - Dashboard usability og fejlrettelser

- [x] Fast dansk navigation med Dashboard som permanent navn
- [x] Tilføj Kom godt i gang med otte deterministiske trin
- [x] Gør Executive Briefing tolerant over for ufarlige JSON-variationer
- [x] Bevar seneste briefing ved teknisk fejl eller ugyldigt modelsvar
- [x] Tilføj websitevalg, datakilder og Kør analyse til AI Analyst
- [x] Forklar manglende data og næste handling på centrale sider
- [x] Tilføj fælles hjælpepanel på alle sider
- [x] Oversæt Website Discovery-signaler til almindeligt dansk

Succeskriterium: en bruger uden kendskab til den interne arkitektur kan finde
næste trin, forstå tomtilstande og skelne datamangel fra tekniske fejl.

## Sprint 25 - Websitebaseret navigation og SEO-visning

- [x] Tilføj et vedvarende globalt websitevalg for aktive websites
- [x] Brug websitekonteksten på profil-, discovery-, content- og analysesider
- [x] Gør Projekter og Opgaver websitefiltrerede med mulighed for at vise alle
- [x] Gør Partner Ads tværgående med et valgfrit websitefilter
- [x] Erstat Websites-placeholderen med et samlet dataoverblik
- [x] Vis SEO pr. website og periode med KPI'er, historik og muligheder
- [x] Hold almindelig SEO-visning fri for API-kald og automatisk projektoprettelse
- [x] Bevar eksplicit Search Console-import med fremdrift og resultat

Succeskriterium: brugeren kan vælge ét aktivt website og følge dets data,
analyser og arbejdsobjekter på tværs af dashboardet uden skjulte eksterne kald.

## Sprint 26 - Stabilisering og samlet driftsstatus

- [x] Ret AI Analyst-visning af resultater uden `created_at`
- [x] Vis den senest gemte analyse efter vellykket kørsel
- [x] Tilføj én-gangs Partner Ads-import med eksisterende dubletregler
- [x] Forklar at permanent overvågning kræver monitorprocessen
- [x] Markér Search Console page og query som ikke implementeret
- [x] Tilføj database- og konfigurationsbaseret Systemstatus
- [x] Markér Automation Engine og Supabase som ikke implementeret
- [x] Vis fejlkategori og næste handling uden rå traceback

Succeskriterium: driftsstatus skelner entydigt mellem klar funktionalitet,
manglende data, delvis implementering og funktioner, der ikke findes endnu.

## Sprint 27 - Opdater alle data og testklar Executive Briefing

- [x] Fjern alle produktionskald til den gamle `record_feature_run`
- [x] Brug `feature_runs` gennem den centrale `save_feature_run`-metode
- [x] Tilføj DataRefreshService med fast rækkefølge og fejlisolering
- [x] Tilføj Opdater alle data med fremdrift og resultatoversigt
- [x] Behold Discovery, Content Explorer og AI-kald som manuelle handlinger
- [x] Tilføj virksomheds- og websiteomfang til Executive Briefing
- [x] Vis basal og anbefalet dataklarhed før websitebriefing

Succeskriterium: brugeren kan opdatere det fælles datagrundlag én gang og
derefter bevidst starte AI Analyst og Executive Briefing for ét website.

## Sprint 28 - Executive Intelligence Engine

- [x] Byg virksomheds- og websitekontekst fra dokumenterede datakilder
- [x] Identificér dataproblemer og muligheder uden opdigtede URL'er
- [x] Gør fokusområder konkrete, målbare og højst 120 minutter
- [x] Vis score, dansk prioritetslabel og prioritetsforklaring
- [x] Vis struktureret datagrundlag, risici og muligheder
- [x] Tilføj Project Manager-kladde uden automatisk udførelse
- [x] Afvis generiske handlinger og ugyldige kritiske felter

Succeskriterium: Executive Briefing forklarer hvad der er vigtigt, hvorfor
det er vigtigt, og én konkret næste handling baseret på tilgængelige data.

## Senere kandidater

- Plausible Analytics
- budget og simpelt regnskab
- Opportunity Score og prioriterede arbejdsordrer
- SEO Manager
- Content Manager
- Webmaster
- Adtraction

Kandidater optages først i en version, når forventet værdi og målemetode er defineret.
# Sprint 29

- Implementeret: Search Console side-, søgeords- og kombinationsimport.
- Implementeret: to 28-dages perioder, API-grænser og idempotent lagring.
- Implementeret: SEO-tabeller, filtre, side→søgeord og konkrete muligheder.
- Implementeret: konkret Executive Briefing-opgave og Project Manager-kladde.
- Senere: paginering ud over de nuværende testgrænser og automatisk
  værdikobling mellem enkelte landingssider og affiliate-salg.
# Sprint 30

- Implementeret: én aktiv beslutning og dokumenteret fravalg.
- Implementeret: approval-gated SEO-eksperimenter med URL-lås.
- Implementeret: 28-dages baseline, typespecifik venteperiode og evaluering.
- Implementeret: én forlængelse ved utilstrækkelige data og gemt læring.
- Implementeret: Eksperimenter-dashboard og sikker Robotland-oprydning.
- Senere: automatisk planlagt evaluering i en eksplicit monitorproces.
# Feature 1 – Title Optimization Pipeline

- Implementeret: automatisk valg af én konkret URL og query.
- Implementeret: read-only title, meta, H1, canonical, ord, links og schema.
- Implementeret: tre title- og tre metaforslag med reviewer og ét repair-kald.
- Implementeret: approval draft, manuel redigering og eksplicit afvisning.
- Implementeret: planlagt eksperiment, baseline, URL-lås og implementeringsknap.
- Senere: tilslutning af en dokumenteret, licenseret SERP-datakilde.

# Opfølgning efter Sprint 4 – Plausible

Disse punkter er registreret til senere prioritering og er ikke implementeret:

- [ ] Tilføj mulighed for at gemme et særskilt Plausible-site-id pr. website,
  så integrationen ikke altid behøver at bruge domænet som site-id.
- [ ] Udvid Dashboardets integrationsstatus med resultat pr. website,
  importperiode, antal oprettede og opdaterede rækker, årsager til overspring
  samt fejl.

# Sprint 38 - Afsluttet

- Produktionsdato: 22. juli 2026
- Produktionscommit: `585e6ec` (`Complete Sprint 38 experiment evaluation and
  read-only dashboard automation`)
- Implementeret: automatisk eksperimentmonitorering og evaluering efter en
  vellykket Search Console-synkronisering.
- Implementeret: regelbaseret resultatklassificering med AI-fortolkning af de
  beregnede resultater.
- Implementeret: sikker håndtering af utilstrækkelige data, retry og idempotent
  genkørsel.
- Implementeret: read-only rendering af Eksperimenter og Executive Briefing.
- Testresultat: 29 relevante monitorerings-, evaluerings-, database-, UX- og
  dashboardtests bestået før produktionssætning.
- Datakontrol: fire tidligere oprettede produktionsrækker blev vurderet som
  legitime data og er derfor bevaret.

# Sprint 43.1 - Search Console-årsagsanalyse

- [x] Sammenlign de seneste to gemte 28-dages perioder på sideniveau.
- [x] Kræv mindst 20 tidligere klik og filtrér små fald under 5 klik eller 5 %.
- [x] Rangér højst fem sider efter dokumenteret kliktab.
- [x] Knyt højst tre faldende søgeord til hver berørt side.
- [x] Klassificér målte signaler som placering, CTR, efterspørgsel eller uklart.
- [x] Gem analysen idempotent uden AI-kald.
- [x] Vis analysen read-only på SEO-siden.

Succeskriterium: AI Office kan forklare et væsentligt organisk trafikfald med
konkrete URL'er, søgeord og før/efter-tal uden at gætte ved lav datamængde.

# Sprint 43.2 - Plausible-trafikanalyse

- [x] Sammenlign to komplette, ikke-overlappende 28-dages perioder.
- [x] Kræv mindst 100 tidligere besøgende.
- [x] Filtrér fald under 20 besøgende eller 10 % som mindre udsving.
- [x] Klassificér vækst, stabilitet, mindre fald og væsentligt fald.
- [x] Gem analysen idempotent uden AI- eller ekstra API-kald.
- [x] Vis manglende data og seneste analyse read-only på SEO-siden.

Succeskriterium: AI Office kan dokumentere, om udviklingen i Search Console
også ledsages af et reelt fald i Plausible-besøgende.

# Sprint 43.3 - Forklarlige opgaveanbefalinger

- [x] Kombinér de seneste gemte 28-dages diagnoser pr. website.
- [x] Skeln mellem kombineret, kun organisk og kun samlet trafikfald.
- [x] Brug vigtigste berørte URL og målt årsag i anbefalingen.
- [x] Erstat generiske dubletter med én specifik kandidat pr. website.
- [x] Beregn og gem prioritet gennem det eksisterende scoringssystem.
- [x] Vis anbefalingen read-only uden automatisk opgaveoprettelse.

Succeskriterium: AI Office kan anbefale én konkret, prioriteret næste handling
og forklare præcist, hvilke målte Search Console- og Plausible-signaler den
bygger på.

# Sprint 43.4 - Opgavekladde og anbefalingsbeslutning

- [x] Opret en redigerbar opgavekladde ved eksplicit brugerklik.
- [x] Hold kladden uden for den operationelle opgavekø.
- [x] Gem website, URL, målt årsag, evidens og prioritet.
- [x] Blokér dubletter mod samme anbefaling og åbne opgaver med samme titel.
- [x] Giv mulighed for at udsætte anbefalingen 14 dage.
- [x] Giv mulighed for eksplicit at afvise anbefalingen.
- [x] Vis en konkret arbejdsplan med søgeord, trin, færdigkriterium,
  tidsestimat og 28-dages måling adskilt fra datagrundlaget.

Succeskriterium: En anbefaling kan gemmes som én redigerbar og sporbar kladde,
udsættes eller afvises uden at oprette, starte eller udføre en operationel
opgave.

# Sprint 43.5 - Godkendelse og 28-dages SEO-eksperiment

- [x] Kræv eksplicit godkendelse af en gemt opgavekladde.
- [x] Hold godkendelse og faktisk websiteimplementering som to adskilte trin.
- [x] Lad brugeren registrere præcist én implementeret ændring og ændringstype.
- [x] Kontrollér stabil Search Console-baseline før eksperimentet oprettes.
- [x] Opret, godkend og start præcist ét SEO-eksperiment idempotent.
- [x] Lås URL'en gennem den eksisterende eksperimentmotor.
- [x] Gem implementeringstidspunkt, eksperiment-id og planlagt evalueringsdato.
- [x] Link direkte fra anbefalingen til den løbende eksperimentmåling.

Succeskriterium: En godkendt anbefaling kan efter manuel websiteændring
registreres som ét sporbart SEO-eksperiment med baseline og en planlagt
28-dages evaluering, uden at appen selv ændrer websitet.

# Sprint 43.6 - Praktisk overblik over igangværende SEO-arbejde

- [x] Saml anbefalingskladder og aktive eksperimenter i Aktuel opgave.
- [x] Vis antal kladder, afventende implementeringer, målinger og evalueringer.
- [x] Giv igangværende arbejde forrang for nye anbefalinger.
- [x] Prioritér næste handling som evaluér, implementér og derefter godkend.
- [x] Vis aktiv måling uden at blokere arbejde på andre ulåste URL'er.
- [x] Undgå dubletter mellem anbefalingsbeslutning og tilknyttet eksperiment.
- [x] Respektér websitefilteret i både beslutninger og eksperimenter.
- [x] Navigér direkte til korrekt website i SEO eller til Eksperimenter.

Succeskriterium: Aktuel opgave viser, hvor hvert SEO-arbejde befinder sig, og
hvilken konkret brugerhandling der kommer først, før appen foreslår nyt arbejde.

# Sprint 44.1 - Enkel start og tydelig navigation

- [x] Gør I dag til appens faktiske startside.
- [x] Begræns den daglige hovednavigation til I dag, Websites, Resultater og
  Portefølje.
- [x] Saml specialistfunktioner under Værktøjer og driftsfunktioner under
  Indstillinger.
- [x] Vis næste trin før status, datagrundlag og tekniske forklaringer.
- [x] Fold sekundære data og øvrigt igangværende arbejde sammen som standard.
- [x] Tilføj kontekstuel hoverhjælp til valg og navigation, hvor konsekvensen
  ikke er selvforklarende.
- [x] Bevar alle eksisterende funktioner og direkte links fra relevante
  arbejdsflows.

Succeskriterium: En ny bruger lander på én konkret arbejdsflade, kan se det
næste trin uden at lede og behøver kun åbne flere sider, når opgaven kræver
specialiseret arbejde eller yderligere dokumentation.

# Sprint 44.2 - Ét samlet opgaveflow

- [x] Godkend en ny trafikanbefaling direkte på I dag uden et synligt
  kladdemellemtrin.
- [x] Bevar redigering, udsættelse og afvisning som sekundære handlinger.
- [x] Vis godkendte opgaver som klar til implementering på samme side.
- [x] Link direkte til den berørte webside og registrér den udførte ændring på
  I dag.
- [x] Start én 28-dages måling fra den registrerede ændring og vis derefter
  måleperioden i det eksisterende overblik.
- [x] Brug enkle brugerstatusser: Klar til godkendelse, Klar til
  implementering, Under måling, Klar til evaluering og Afsluttet.
- [x] Genlæs gemte anbefalingsbeslutninger sikkert efter Streamlit hot reload.
- [x] Flyt Partner Ads fra sidebaren til Integrationer og behold detaljesiden
  via et kontekstuelt link.

Succeskriterium: Brugeren kan gå fra anbefaling til aktiv 28-dages måling via
I dag uden at navigere gennem andre AI Office-sider; kun selve websitet åbnes
for den manuelle ændring.

# Sprint 44.3 - Faste roller og færre gentagelser

- [x] Fastlæg fire primære informationshjem: I dag for handling,
  Website Profile for ét sites status, Portefølje for tværgående overblik og
  Resultater for målinger og læring.
- [x] Gør SEO til analyse og dokumentation uden et parallelt opgaveflow.
- [x] Skjul tekniske og historiske detaljer på Website Profile som standard.
- [x] Forkort Kom godt i gang fra otte tekniske trin til fire brugertrin.
- [x] Send ældre projekt-, opgave- og briefingvisninger tydeligt tilbage til
  I dag.
- [x] Fjern Executive Briefing som næste handling efter dataopdatering.
- [x] Tilføj hoverhjælp til websitevalget og et synligt næste trin på de
  centrale flader.

Succeskriterium: Brugeren ved, hvilken side der ejer hvilken information, og
kan altid fortsætte til den konkrete opgave uden at møde en parallel handling
eller en blindgyde.

# Sprint 44.4 - Ét samlet resultat- og læringsflow

- [x] Saml aktive målinger, afsluttede resultater og dokumenteret læring på
  Resultater.
- [x] Vis først en enkel status med forbedret, uændret og forværret.
- [x] Vis næste handling for hvert afsluttet resultat.
- [x] Bevar før- og efterdata i fold-ud-sektioner.
- [x] Vis dokumenterede læringsmønstre og deres datakvalitet som sekundær
  information.
- [x] Gør SEO Insights og SEO-læring til udfasede henvisningssider.
- [x] Fjern SEO-læring fra navigationen.
- [x] Bevar Resultater som den eneste brugerflade for målinger og læring.

Succeskriterium: Brugeren kan følge hele kæden fra aktiv måling til konklusion
og genbrugelig læring på én side og ved altid, om ændringen skal bevares,
tilpasses, tilbageføres eller blot afvente flere data.

# Sprint 44.5 - Konkrete AI-leverancer før godkendelse

- [x] Kræv et konkret arbejdsudkast før en ny opgave kan godkendes.
- [x] Brug samme leveranceformat til title/meta, indhold, interne links,
  tekniske rettelser, schema og trafikanalyse.
- [x] Vis AI Offices anbefalede løsning, alternativer, begrundelse,
  implementering og kontrolpunkter direkte på I dag.
- [x] Lad brugeren kontrollere og redigere den anbefalede løsning før
  godkendelse.
- [x] Gem den godkendte konkrete leverance som opgavens arbejdsbeskrivelse.
- [x] Bevar manuel implementering og eksplicit start af målingen.
- [x] Brug et tydeligt regelbaseret nødudkast, hvis AI-forbindelsen fejler.
- [x] Fjern muligheden for at godkende en generel arbejdsbeskrivelse uden
  konkrete forslag.

Succeskriterium: AI Office udfører forarbejdet for alle opgavetyper. Brugeren
skal kontrollere, eventuelt redigere og godkende en færdig leverance – aldrig
selv begynde med at skrive forslagene eller udføre den indledende analyse.
