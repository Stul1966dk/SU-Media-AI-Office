# Systemstatus og dataopdatering

## Opdater alle data

Dashboardets centrale opdatering kører:

1. Website Registry
2. Partner Ads
3. Search Console-properties
4. Search Console-dagstal
5. Search Console-sider og søgeord
6. SEO History
7. Website Intelligence
8. Systemstatus

Website Discovery og Content Explorer er valgfrie manuelle trin. AI Analyst
og Executive Briefing startes heller ikke automatisk.

Hvis Search Console fejler, springes dagstal og SEO History over. Partner Ads,
Website Intelligence og systemstatus forsøges fortsat.

Den normale Search Console-dagstalsimport er trinvis. For hvert tilknyttet
website genhentes et overlap, der starter fem kalenderdage før seneste gemte
dato. Websites uden eksisterende dagstal bruger 35 dage, og den eksplicitte
manuelle Search Console-import bruger ligeledes en tvungen 35-dagesperiode.
Ældre historiske dagstal hentes ikke igen ved normal synkronisering.

## Feature runs

Tabellen `feature_runs` gemmer funktionsnavn, status, start, afslutning,
behandlede, oprettede og opdaterede poster samt en saniteret fejltype og
fejlbeskrivelse. `Database.save_feature_run()` er den eneste skriveindgang.

En fejl ved registrering af kørselsstatus ændrer aldrig resultatet af en
vellykket Partner Ads-import.

## Executive Briefing

Websitebriefing kræver Registry, Website Profile, mindst 14 gemte Search
Console-dage og en fungerende OpenAI-forbindelse. Ved tilstrækkelige basale,
men manglende anbefalede data vises status **Delvist klar**, og briefingen
forklarer, at page- og query-data endnu ikke importeres.

## Decision Engine og SEO Experiment Engine

Decision Engine er klar, når der findes to sammenlignelige Search
Console-perioder på URL-niveau. SEO Experiment Engine kræver en konkret URL
og mindst 14 dages stabil baseline. Begge funktioner er godkendelsesstyrede og
foretager ingen websiteændringer.

## Title Optimization Pipeline

Klar til test, når det aktive monetized website har to 28-dages Search
Console-perioder på page- og query-niveau samt offentlig adgang til URL'en.
OpenAI genererer forslag; den lokale reviewer og brugerens godkendelse er
obligatoriske. SERP-konkurrentdata er valgfri og markeres som en begrænsning,
når ingen lovlig kilde er konfigureret.
