# SU Media AI Office

## Stabilitetsaudit

Kør den skrivebeskyttede integritetskontrol med:

```powershell
python scripts/audit_system.py
```

Sikre reparationer kræver flaget `--repair-safe`. Se
`docs/sprint-37-stability-audit.md` for kontroller og kendte begrænsninger.

SU Media AI Office er SU Medias digitale organisation. Systemet skal hjælpe CEO med at træffe bedre beslutninger hurtigere og prioritere den arbejdstid, der forventes at skabe størst målbar værdi.

Det langsigtede forretningsmål er en stabil gennemsnitlig månedsindtægt på 20.000-25.000 kr., så SU Media på sigt kan blive en fuldtidsforretning.

## Første leverance

Version 0.1 skal:

1. kontrollere Partner-ads hvert 30. minut,
2. opdage nye salg uden dubletter,
3. gemme salg,
4. sende en Telegram-notifikation ved hvert nyt salg.

Første version er primært en sikker automatisering. AI tilføjes, når der findes data, som kræver analyse, prioritering eller forklaring.

## Grundprincip

En opgave er først afsluttet, når effekten er målt. Hvis en funktion ikke forventes at øge indtjeningen, forbedre beslutninger eller spare væsentlig tid, skal den ikke prioriteres.

## Projektstruktur

- `dashboard/` - read-only Streamlit-dashboard og placeholdersider
- `docs/` - virksomhedsviden, arkitektur, standarder og roadmap
- `agents/` - roller og ansvar for AI-medarbejdere
- `integrations/` - forbindelser til eksterne datakilder
- `services/` - fælles tekniske tjenester
- `loops/` - målbare feedback-loops

## Web Dashboard

Installer afhængigheder og start dashboardet fra projektets rod:

```powershell
python -m pip install -r requirements.txt
streamlit run dashboard/app.py
```

Dashboardet åbner som standard på [http://localhost:8501](http://localhost:8501). Det læser kun den lokale SQLite-database gennem `core.database.Database`; det starter ingen Search Console-, Partner Ads-, OpenAI- eller Telegram-kald. Siden **Website Profile** samler profil, SEO, provision, historik, aktive projekter/opgaver og gemte anbefalinger for et valgt website. Siden **AI Analyst** viser de seneste analyser og hele den valgte rapport.

Databasen findes som standard i `data/affiliate_manager.db`. En anden lokal database kan vælges med miljøvariablen `SU_MEDIA_DATABASE_PATH`.

## OpenAI-forbindelse

Sæt `OPENAI_API_KEY` som miljøvariabel før AI Office startes. Nøglen må ikke skrives i kildekode, logfiler eller databasen.

```powershell
$env:OPENAI_API_KEY = "din-api-nøgle"
python src/main.py
```

Forbindelsestesten bruger OpenAI Responses API og sender kun en fast testinstruktion uden virksomheds-, Search Console- eller salgsdata. Standardmodellen er `gpt-5.6-terra`; den kan om nødvendigt vælges med `OPENAI_MODEL`. Dashboardet viser den senest gemte forbindelsesstatus og foretager ikke selv API-kald.

## AI Analyst

`agents/ai_analyst.py` samler gemte websiteprofiler, SEO Health, Search Console-historik, Partner Ads-historik, projekter, opgaver og de relevante Knowledge Engine-regler i en automatisk saniteret prompt. Agenten analyserer websites, projekter og opgaver og kan gennemføre en daglig analyse af aktive websites.

Modellen skal returnere valideret JSON. Et ugyldigt svar prøves én gang mere; to ugyldige svar gemmes som en fejlrapport. Analyser gemmes med model, tokenforbrug og svartid. AI Analyst opretter eller ændrer aldrig projekter, opgaver, websites eller WordPress. Confidence klassificerer alene anbefalingen til forslag, anbefaling eller SEO Manager-gennemgang.

## Status

AI Office indeholder nu Search Console-import, SEO History, SEO Manager, Website Intelligence, AI Analyst, en sikker OpenAI-forbindelse og et lokalt read-only Streamlit-dashboard.

## AI Executive

`agents/ai_executive.py` samler gemte website-, salgs-, SEO-, projekt-,
opgave- og analysedata med virksomhedens playbook. Den scorer dokumenterede
muligheder fra 0-100 og foreslår højst tre konkrete fokusområder. Et forslag
udfører intet: det opretter ingen projekter eller opgaver, ændrer ingen
websites og sender ingen beskeder. Siden **Executive Briefing** kan starte
analysen og viser den senest gemte briefing.

## Website Discovery

`agents/website_discovery.py` opbygger en teknisk faktaprofil fra et fast,
begrænset sæt offentlige endpoints. Scanneren bruger User-Agent
`SU-Media-AI-Office/0.1 Website Discovery`, ti sekunders timeout og gemmer
aldrig HTML, cookies eller credentials. Scanning starter kun efter et klik på
siden **Website Discovery**. Fund kan oprette en pending orchestrator-hændelse,
men aldrig projekter, opgaver eller ændringer på websitet.

## Connector Framework

`connectors/` indeholder et generelt read-only interface og den første
implementation, `WordPressConnector`. Connectoren bruger offentlig REST API
og falder automatisk tilbage til offentlig HTML. Content Explorer kan efter
brugerklik importere og udforske indlæg, sider, kategorier, tags og medier.
Kun ændrede elementer opdateres. Se [connector-dokumentationen](docs/connectors.md).

## Dashboard og arbejdsgang

Dashboardet har én fælles dansk navigation og siden **Kom godt i gang**, som
viser den faste rækkefølge fra Website Registry til projekter og opgaver.
Alle sider forklarer formål, krav, mulige handlinger og begrænsninger.
Executive Briefing bevarer den seneste gyldige briefing ved en ny fejl, mens
AI Analyst kan startes direkte efter valg af website og viser sit
datagrundlag før analysen.

Search Console kan startes manuelt fra siden **SEO** med knappen **Hent Search
Console-data**. Handlingen opdager og matcher properties, importerer de seneste
35 kalenderdage og viser importerede websites, website-dage og fejl, før
dashboardet genindlæses.

## Websitebaseret dashboard

Sidepanelets fælles websitevælger gemmer det aktive domæne på tværs af
Website Profile, Website Discovery, Content Explorer, SEO, AI Analyst,
Projekter og Opgaver. Udfasede, arkiverede og annullerede websites kan ikke
vælges. Websites-siden giver tværgående overblik, mens SEO-siden læser gemte
data for 7, 28, 90 eller 365 dage. Eksterne Search Console-kald sker kun,
når brugeren klikker **Hent Search Console-data**.

## Stabilisering og driftsstatus

Siden **Systemstatus** samler implementeringsstatus, datakilde, startmetode,
seneste vellykkede kørsel, begrænsning og næste trin. Status kombinerer
implementeringsviden med databaseindhold, gemte servicekontroller og lokal
konfiguration.

Partner Ads kan hentes én gang fra Partner Ads-siden med den samme
idempotente kontrol- og notifikationslogik som monitorprocessen. Permanent
overvågning startes fortsat kun med `python src/main.py`. Search
Console-fanerne Top sider og Top søgeord er markeret som ikke implementeret,
fordi den nuværende import kun gemmer dagstal pr. website.

## Opdater alle data

Dashboardets knap **Opdater alle data** kører Website Registry, Partner Ads,
Search Console-properties, Search Console-dagstal, SEO History, Website
Intelligence og systemstatus i en fast rækkefølge. Trinfejl isoleres, mens
direkte afhængigheder springes over med en forklaring. Website Discovery og
Content Explorer forbliver valgfrie, manuelle trin.

Opdateringen starter ingen AI-analyser og genererer ingen briefing.
Executive Briefing kan efterfølgende afgrænses til hele virksomheden eller
det aktive website og viser en dataklarhedskontrol før generering.

## Executive Intelligence

Executive Briefing kombinerer modeloutput med deterministisk
Executive Intelligence. Hvert fokusområde viser konkrete data, en handling
på højst 120 minutter, ansvarlig agent, forventet effekt, prioritet,
confidence, målemetode og kendte begrænsninger. Manglende URL- og
søgeordsdata må ikke erstattes af opdigtede sider eller søgeord.

Risici og muligheder vises som strukturerede kort. Et fokusområde kan sendes
til Project Manager som en kladde; handlingen starter aldrig arbejdet.
# Search Console på side- og søgeordsniveau

Den manuelle Search Console-import og **Opdater alle data** henter nu både
dagstal, sider, søgeord og kombinationer af side + søgeord. Importen er
read-only og gemmer den seneste samt den foregående komplette 28-dages
periode. I testversionen er standardomfanget kun det aktive website; brugeren
kan eksplicit vælge alle aktive websites.

Grænser pr. website og periode er 1.000 sider, 2.000 søgeord og 5.000
side-/søgeordskombinationer. Rækker prioriteres efter klik og visninger.
# Decision Engine og SEO-eksperimenter

AI Office vælger nu højst én aktiv, konkret SEO-beslutning ad gangen.
Beslutningen er baseret på URL- og søgeordsdata, datavolumen, trafikændring,
monetization, risiko og eksisterende arbejde. Manuel websiteprioritet er kun
én mindre del af scoren.

**Send til Project Manager** opretter ét projekt, én opgave og ét planlagt
eksperiment med status *Afventer godkendelse*. Intet starter automatisk.
Eksperimentet kræver mindst 14 dages stabil URL-baseline og låser URL'en efter
godkendelse, indtil evalueringen er afsluttet eller eksperimentet annulleres.
# Title Optimization Pipeline

Siden **Title optimering** vælger én monetized, ulåst URL med placering 3-15,
tilstrækkelige visninger og lav CTR. Flowet læser den offentlige side, bevarer
nuværende title og meta, genererer præcis tre danske forslag af hver type og
lader en regelbaseret reviewer kontrollere længde, overlap, spam, keyword
stuffing og udokumenterede superlativer.

Godkendelse opretter én manuel implementeringsopgave og ét planlagt
SEO-eksperiment med gemt baseline. URL'en låses, men eksperimentets måleperiode
starter først, når brugeren klikker **Markér som implementeret**. AI Office
publicerer aldrig ændringen.
