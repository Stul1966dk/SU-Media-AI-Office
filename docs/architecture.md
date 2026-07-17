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

## Sikkerhed

Tokens, API-nøgler, Chat ID'er og andre hemmeligheder må aldrig gemmes i dokumentation eller versionsstyret kode. De skal senere placeres i sikker lokal konfiguration eller et secrets-system.
