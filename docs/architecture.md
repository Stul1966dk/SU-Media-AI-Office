# Arkitektur

Status: Godkendt som arkitekturbeslutning 001.

## Formål

Arkitekturen skal være enkel i første version og kunne udvides uden at gøre de enkelte AI-medarbejdere til isolerede systemer.

## Overordnet dataflow

```text
Datakilder
  -> Integrationer
  -> Fælles hukommelse/database
  -> Regler, analyse og prioritering
  -> AI-medarbejdere
  -> Handlinger og arbejdsordrer
  -> Måling og læring
  -> tilbage til analyse og prioritering
```

## Lag

### Datakilder

Planlagte kilder er Partner-ads, Google Search Console, Plausible Analytics samt budget og regnskab. De tilføjes kun, når en konkret funktion kræver dem.

### Integrationer

Hver integration henter og validerer data, normaliserer formatet, håndterer fejl og understøtter kontrol af dubletter. Integrationer giver ikke strategiske råd.

### Fælles hukommelse

Systemet skal med tiden gemme salg, trafik, websites, arbejdsordrer, beslutninger, målinger og dokumenterede erfaringer. Fakta, hypoteser, beslutninger og resultater skal holdes adskilt.

Den centrale databaseadgang ligger i `core/database.py`. Klassen `Database` er den eneste komponent, der må indeholde SQL eller arbejde direkte med SQLite. Affiliate Manager og fremtidige AI-medarbejdere bruger klassens offentlige metoder til initialisering, dubletkontrol, lagring og læsning af salg.

Denne grænse holder forretningslogikken uafhængig af den aktuelle database og gør en senere migration fra SQLite til Supabase PostgreSQL enklere.

Website Registry ligger i `core/website_registry.py`. Komponenten importerer og normaliserer websiteoplysninger fra CSV, mens den centrale `Database` udfører lagring og opslag. Andre komponenter bruger registret via metoderne `get_all()` og `get()` og behøver derfor ikke kende CSV-filens placering eller format.

Registry-synkroniseringen kører automatisk ved Affiliate Managers opstart. Importen sammenligner de normaliserede CSV-data med den eksisterende `websites`-tabel og returnerer et struktureret resultat med antal fundne, oprettede, opdaterede og nyligt udfasede websites. Manglende eller ugyldig CSV vises som en advarsel og må ikke stoppe salgsmonitoreringen.

### Beslutningslag

Faste og entydige kontroller løses med programregler. AI anvendes til fortolkning, forklaring og prioritering, hvor der reelt er behov for dømmekraft.

Decision Engine v0.1 ligger i `agents/decision_engine.py` og bruger den centrale `Database` og `WebsiteRegistry`. Den vurderer kun aktive websites, der ikke er markeret som `phasing_out`, og vælger én anbefaling med en transparent regelbaseret score.

Scoren bruger websiteprioritet, monetization og handlingssignaler i noter: `needs design`, `needs content`, `high potential` og `drop`. Resultatet indeholder website, begrundelse, score og anbefalet handling og vises ved programmets opstart.

Project Manager ligger i `agents/project_manager.py` og omsætter projekter til ordnede delprojekter og konkrete opgaver. Task Engine i `core/task_engine.py` håndhæver statusværdier, maksimalt 120 minutters varighed, afhængigheder og opgavernes lifecycle. SQL for projekter og opgaver forbliver i den centrale `Database`.

Decision Engine kan returnere en projektanbefaling eller en opgave. Når der findes planlagte opgaver, er det altid Project Manager, der vælger den konkrete næste opgave med opfyldte afhængigheder.

### AI-medarbejdere

Affiliate Manager er første medarbejder. Senere kan SEO Manager, Content Manager og Webmaster bruge samme hukommelse, standarder og fælles tjenester.

### Handlinger

Handlinger kan være Telegram-notifikationer, advarsler, rapporter og konkrete arbejdsordrer. Eksterne eller risikofyldte handlinger kræver de nødvendige rettigheder og eventuel godkendelse fra CEO.

## Version 0.1

```text
Partner-ads XML
  -> Partner-ads-integration
  -> central Database-klasse
  -> SQLite-salgslager
  -> kontrol af nye salg
  -> Notification Service
  -> Telegram
```

Version 0.1 indeholder ikke et fleragentsystem eller en avanceret beslutningsmotor.

## Website Registry

```text
Website-CSV
  -> WebsiteRegistry
  -> domænenormalisering og validering
  -> central Database-klasse
  -> websites-tabel
  -> AI-medarbejdere og fælles tjenester
```

Domænet er den unikke nøgle. Gentagne importer opdaterer eksisterende websites og opretter kun poster for nye domæner.

Websites, der ikke længere findes i CSV-filen, slettes ikke automatisk. Dermed bevares historik og oplysninger, indtil en særskilt, kontrolleret sletning gennemføres.

## Decision Engine v0.1

```text
Website Registry + Database
  -> filtrering af active og phasing_out
  -> regelbaseret scoring
  -> højeste anbefaling
  -> terminalvisning
```

## Project Manager og Task Engine

```text
Projekt
  -> Project Manager
  -> ordnede delprojekter
  -> konkrete opgaver på højst 120 minutter
  -> Task Engine
  -> afhængigheds- og statuskontrol
  -> næste udførbare opgave
```

## AI Office Dashboard

Opstartsskærmen samles af `core/dashboard.py`. Dashboardet læser aggregerede nøgletal gennem den centrale `Database` og viser websites, provision, aktive projekter, åbne opgaver og Project Managers næste konkrete opgave.

```text
Website Registry + salg + projekter + opgaver
  -> central Database
  -> Dashboard
  -> samlet opstartsskærm
```

Tekniske hændelser som registry-synkronisering, Partner-ads-kontroller, fejl og tidspunktet for næste kontrol skrives til `logs/affiliate_manager.log`. Terminalen bruges til den operationelle oversigt, en eventuel fatal opstartsfejl og bekræftelse ved stop med `Ctrl+C`.

## Knowledge Engine

Knowledge Engine ligger i `core/knowledge_engine.py` og indekserer den fælles Markdown-viden under `knowledge/`. Motoren leverer dokumenter, kategorier, søgning og virksomhedsregler uden at kende eller importere de enkelte AI-agenter.

```text
knowledge/company + seo + wordpress + affiliate + development
  -> Knowledge Engine
  -> kategoriseret og søgbar viden
  -> fælles adgang for AI Office-komponenter
```

Dashboardet initialiserer Knowledge Engine ved opstart og viser status samt antal fundne dokumenter. Kategoridokumenterne er de centrale kilder til regler; agentspecifik beslutningslogik forbliver uden for Knowledge Engine.

## Agent Orchestrator

Agent Orchestrator ligger i `core/agent_orchestrator.py` og er det centrale, agent-neutrale routinglag. Den kender de fælles engines og registrerede agenters kapabiliteter, men indeholder ikke specialistlogik for SEO, indhold, design eller affiliate.

```text
Hændelse
  -> Agent Orchestrator
  -> kapabilitetsbaseret routing i fast rækkefølge
  -> en eller flere persistente handlinger
  -> afhængighedskæde
  -> specialagent
  -> gemt resultat og frigivelse af næste handling
```

Hændelser og handlinger gemmes i SQLite-tabellerne `events` og `actions`. En handling med en ufærdig forgænger har status `blocked`; når forgængeren færdigmarkeres, ændres den næste til `pending`. Dashboardet viser ventende hændelser, ventende handlinger og antal registrerede agenter.

## Google Search Console

Den read-only Search Console-integration ligger i `integrations/search_console.py`. Et eksplicit desktop OAuth-login bruger den lokale `credentials.json` og gemmer tokenet i `token.json`. Den normale dataimport kræver og genbruger `token.json`; den starter aldrig et browser-login automatisk. Begge filer er udelukket fra Git.

`core/search_console_service.py` henter property-listen, matcher property-domæner med Website Registry og gemmer resultatet gennem den centrale `Database`. Kun aktive properties med et website-match får hentet Search Analytics-data. Den automatiske import forespørger de seneste 180 dage med datodimension, så SEO History Engine har grundlag for 90 mod 90 dage, og gemmer ét samlet dagspunkt pr. website. En fejl isoleres til den enkelte property og logges kun med property-navn og exceptiontype.

```text
Google OAuth (read-only)
  -> SearchConsoleConnector
  -> SearchConsoleService
  -> Website Registry-domænematch
  -> search_console_properties
  -> Search Analytics API (daglige totaler)
  -> search_console_daily_metrics
  -> SEO History Engine (7/28/90 dage mod foregående periode)
  -> seo_health_history
  -> Dashboard
```

`core/seo_history.py` beregner en deterministisk `SEOHealth` for hvert website og hver periode. Scoren er afgrænset til 0-100 med 50 som neutral baseline og klassificeres som `growing`, `stable`, `declining` eller `critical`. Klik og visninger måles som procentændringer, CTR som procentpoint og placering som forskellen i vægtet gennemsnitsplacering. Manglende sammenligningsgrundlag behandles neutralt.

Dashboardet viser forbindelsesstatus, property-antal, seneste synkronisering, antal gemte dagspunkter og fordelingen af 28-dages SEO Health. Terminalen viser importresultatet, op til fem websites med størst fald i klik og de fem laveste 28-dages SEO-scorer. Analysen opretter ingen opgaver eller Orchestrator-hændelser, bruger ikke Project Manager og sender ingen Telegram-beskeder.

## SEO Manager

`agents/seo_manager.py` er den første specialistagent. Den bruger 28-dages `SEOHealth` og ignorerer websites med status `phasing_out`, `archived` eller `cancelled`. Et recovery-projekt kræver dokumenteret forværring: score under 35, `critical` trend, mindst 25 procent klikfald eller mindst 15 procent klikfald kombineret med dårligere placering eller CTR.

```text
SEO History (28d)
  -> SEO Manager
  -> seo_recommendations
  -> SEO Recovery-projekt (opret eller opdater)
  -> seks faste delprojekter
  -> fem korte, afhængige startopgaver
  -> seo_recovery_project_created event ved nyt projekt
  -> Agent Orchestrator
```

Projektidentiteten er kombinationen af website og titlen `SEO Recovery – [website]`. En eksisterende projektpost opdateres og genbruges, og allerede oprettede startopgaver duplikeres ikke. Startopgaverne indeholder målemetode, varer højst 120 minutter og fordeles mellem SEO Manager, Webmaster og Content Manager.

SEO Manager må kun analysere, anbefale og planlægge. Den har ingen website-skrivevej og sender ingen Telegram-beskeder. Dashboard og terminal viser antal analyserede websites, nye og opdaterede recovery-projekter, websites uden handling samt den højest prioriterede anbefaling.

## Web Dashboard

Sprint 17 tilføjer et lokalt Streamlit-dashboard i `dashboard/`. `dashboard/app.py` er indgangspunktet, `dashboard/components/` indeholder data- og UI-komponenter, `dashboard/pages/` indeholder placeholdersider, og `dashboard/assets/` indeholder det mørke responsive tema.

```text
Streamlit UI
  -> dashboard.components.data
  -> Database read-only facade
  -> SQLite
```

UI-laget indeholder ingen SQL og importerer ingen eksterne integrationer. Alle sektioner læses via `Database`-metoder for systemstatus, overblik, økonomi, SEO Health, vigtigste opgaver, SEO Recovery, seneste salg og Orchestrator-events. En sektion med tomme eller utilgængelige data viser `Ingen data.` uden at blokere de øvrige sektioner.

Dashboardprocessen foretager ingen Telegram-, Search Console- eller Partner Ads-kald. De eksisterende baggrundsprocesser gemmer seneste kendte komponentstatus i `app_state`, som dashboardet læser sammen med de øvrige databaseværdier.

## Website Intelligence

`agents/website_intelligence.py` opbygger én samlet, deterministisk profil pr. website ud fra allerede gemte data. Agenten læser Website Registry, Search Console-dagstal, Partner Ads-salg, 28-dages SEO Health og aktive projekter/opgaver gennem `Database`.

```text
Website Registry + gemte driftsdata
  -> Website Intelligence Agent
  -> website_profiles
  -> website_statistics
  -> website_categories
  -> website_history
  -> Website Profile (Streamlit, read-only)
```

`website_profiles` holder den aktuelle profil og website health. `website_statistics` gemmer daglige sammenkoblede målinger. `website_categories` gemmer niche- og monetization-kategorier. `website_history` gemmer kun snapshots, når data faktisk ændres. CMS og tema registreres fra eksisterende metadata; ukendte værdier gemmes som `Ukendt` og gættes ikke.

Website Profile-siden åbner et website via en selector og viser profil, SEO, provision, historik, aktive projekter, aktive opgaver og de gemte deterministiske anbefalinger. Siden har ingen SQL og kalder ingen eksterne tjenester.

## Sikkerhed

Tokens, API-nøgler, Chat ID'er og andre hemmeligheder må aldrig gemmes i dokumentation eller versionsstyret kode. De skal senere placeres i sikker lokal konfiguration eller et secrets-system.
