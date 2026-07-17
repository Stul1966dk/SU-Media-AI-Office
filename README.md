# SU Media AI Office

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

Dashboardet åbner som standard på [http://localhost:8501](http://localhost:8501). Det læser kun den lokale SQLite-database gennem `core.database.Database`; det starter ingen Search Console-, Partner Ads- eller Telegram-kald. Siden **Website Profile** samler profil, SEO, provision, historik, aktive projekter/opgaver og gemte anbefalinger for et valgt website.

Databasen findes som standard i `data/affiliate_manager.db`. En anden lokal database kan vælges med miljøvariablen `SU_MEDIA_DATABASE_PATH`.

## Status

AI Office indeholder nu Search Console-import, SEO History, SEO Manager, Website Intelligence og et lokalt read-only Streamlit-dashboard.
