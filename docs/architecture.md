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

### Beslutningslag

Faste og entydige kontroller løses med programregler. AI anvendes til fortolkning, forklaring og prioritering, hvor der reelt er behov for dømmekraft.

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

## Sikkerhed

Tokens, API-nøgler, Chat ID'er og andre hemmeligheder må aldrig gemmes i dokumentation eller versionsstyret kode. De skal senere placeres i sikker lokal konfiguration eller et secrets-system.
