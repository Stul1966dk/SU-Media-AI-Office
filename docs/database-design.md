# Databasedesign

## Formål

Databasen skal fungere som fælles hukommelse for SU Media AI Office. Den skal samle data om blandt andet websites, affiliatesalg, opgaver, målinger og anbefalinger, så systemets AI-medarbejdere kan arbejde ud fra det samme datagrundlag.

Databasen udvikles først lokalt i SQLite. Strukturen skal udformes, så den senere kan flyttes til Supabase PostgreSQL uden en omfattende omlægning af data eller forretningslogik.

## Nuværende løsning

Den nuværende løsning bruger SQLite og kører lokalt sammen med Affiliate Manager. Databasefilen ligger her:

```text
data/affiliate_manager.db
```

Databasefilen gemmes ikke på GitHub. Den er en lokal driftsfil og er udelukket via projektets `.gitignore`.

Tabellen `registered_sales` indeholder de Partner-ads-salg, som Affiliate Manager allerede har behandlet. Feltet `kombiid` bruges som unik nøgle, så det samme salg ikke registreres eller udløser en Telegram-notifikation flere gange.

Tabellen gemmer følgende felter for hvert registreret salg:

| Felt | Beskrivelse |
| --- | --- |
| `kombiid` | Salgets unikke ID fra Partner-ads og tabellens primære nøgle |
| `programid` | Partner-ads-programmets ID |
| `program` | Partner-ads-programmets navn |
| `dato` | Salgets dato |
| `tidspunkt` | Salgets tidspunkt |
| `ordrenr` | Ordrenummeret |
| `omsaetning` | Salgets omsætning som numerisk værdi |
| `provision` | Salgets provision som numerisk værdi |
| `url` | Websitet eller kilden knyttet til salget |
| `valuta` | Salgets valutakode |
| `created_at` | Tidspunktet, hvor salget blev registreret lokalt |

Affiliate Manager migrerer automatisk en eksisterende `registered_sales`-tabel, hvis en eller flere af disse kolonner mangler. Eksisterende registreringer og deres unikke ID'er bevares under migrationen.

Tabellen `websites` er det centrale register over de websites, som SU Media AI Office arbejder med. Feltet `website` indeholder et normaliseret domæne og er tabellens unikke nøgle. En ny CSV-import opdaterer alle felter for et eksisterende domæne og opretter en post, når domænet ikke findes.

Ved programstart sammenlignes CSV-data med tabellen felt for felt. Importresultatet registrerer antal fundne, nye, opdaterede og nyligt markerede `phasing_out`-websites. Poster slettes ikke automatisk, hvis de fjernes fra CSV-filen.

| Felt | Beskrivelse |
| --- | --- |
| `website` | Normaliseret domæne og tabellens primære nøgle |
| `display_name` | Navnet, der vises for brugere og AI-medarbejdere |
| `active` | Om websitet er aktivt |
| `monetized` | Om websitet aktuelt er monetiseret |
| `priority` | Websitets prioritet |
| `primary_income_source` | Den primære indtægtskilde |
| `niche` | Websitets niche |
| `domain_age` | Den registrerede dato eller alder for domænet |
| `notes` | Supplerende noter |
| `status` | `active` eller `phasing_out`, afledt af CSV-feltet `notes` |

## Principper

- Rå data gemmes, så de oprindelige værdier kan genbehandles og kontrolleres senere.
- Unikke ID'er bruges til at forhindre dubletter.
- Beløb gemmes som tal og ikke som formateret tekst. Dansk decimalkomma og tusindtalsseparator anvendes kun ved visning.
- Datoer og tidspunkter gemmes i et ensartet format, der kan sorteres og konverteres sikkert.
- Hemmelige oplysninger som API-nøgler, tokens og adgangskoder må ikke gemmes i databasen.
- Ændringer og resultater skal kunne måles over tid, så effekten af opgaver og anbefalinger kan dokumenteres.

## Planlagte tabeller

### `affiliate_sales`

Indeholder normaliserede salg fra Partner-ads og senere andre affiliatenetværk.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `external_id` | Salgets unikke ID hos affiliatenetværket |
| `network` | Kildenetværk, eksempelvis Partner-ads |
| `program_id` | Affiliateprogrammets eksterne ID |
| `program_name` | Affiliateprogrammets navn |
| `website_id` | Reference til det tilknyttede website |
| `order_number` | Ordrenummer hos annoncøren |
| `revenue` | Salgets omsætning som numerisk værdi |
| `commission` | Optjent provision som numerisk værdi |
| `currency` | Valutakode, eksempelvis DKK |
| `sale_date` | Salgsdato i ensartet format |
| `sale_time` | Salgstidspunkt i ensartet format |
| `source_url` | URL eller kilde knyttet til salget |
| `created_at` | Tidspunktet, hvor posten blev oprettet |

### `projects`

Indeholder overordnede projekter knyttet til et website.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `website_id` | Reference til projektets website |
| `title` | Projektets titel |
| `description` | Projektets beskrivelse |
| `status` | Lifecycle-status |
| `priority` | Projektets prioritet |
| `expected_effect` | Forventet effekt |
| `created_at` | Oprettelsestidspunkt |
| `completed_at` | Afslutningstidspunkt |

### `subprojects`

Indeholder de ordnede dele af et projekt.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `project_id` | Reference til det overordnede projekt |
| `title` | Delprojektets titel |
| `description` | Delprojektets beskrivelse |
| `status` | Lifecycle-status |
| `sequence` | Delprojektets rækkefølge |
| `created_at` | Oprettelsestidspunkt |
| `completed_at` | Afslutningstidspunkt |

### `tasks`

Indeholder konkrete, tildelte arbejdsopgaver på højst 120 minutter.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `subproject_id` | Reference til delprojektet |
| `website_id` | Reference til opgavens website |
| `title` | Opgavens titel |
| `description` | Konkret beskrivelse |
| `reason` | Begrundelse for opgaven |
| `assigned_agent` | Ansvarlig AI-medarbejder |
| `estimated_minutes` | Forventet tidsforbrug, maksimalt 120 minutter |
| `expected_effect` | Forventet effekt |
| `priority_score` | Beregnet prioritet |
| `status` | Lifecycle-status |
| `depends_on_task_id` | Eventuel opgave, som først skal færdiggøres |
| `created_at` | Oprettelsestidspunkt |
| `started_at` | Starttidspunkt |
| `completed_at` | Afslutningstidspunkt |

Projekter, delprojekter og opgaver bruger statusværdierne `planning`, `ready`, `in_progress`, `blocked`, `completed` og `cancelled`.

### `events`

Indeholder ensartede hændelser, der skal routes af Agent Orchestrator.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `event_type` | Hændelsens type |
| `source` | Komponenten eller datakilden bag hændelsen |
| `website` | Berørt website |
| `title` | Kort titel |
| `description` | Beskrivelse af hændelsen |
| `priority` | Numerisk prioritet |
| `data_json` | Strukturerede supplerende data |
| `status` | Hændelsens lifecycle-status |
| `created_at` | Oprettelsestidspunkt |
| `processed_at` | Tidspunkt for routing |

### `actions`

Indeholder agenthandlinger oprettet fra en hændelse.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `event_id` | Reference til den udløsende hændelse |
| `action_type` | Handlingens type |
| `assigned_agent` | Den ansvarlige registrerede agent |
| `website` | Berørt website |
| `project_id` | Eventuel reference til et projekt |
| `task_id` | Eventuel reference til en opgave |
| `reason` | Begrundelse for routingen |
| `priority` | Numerisk prioritet |
| `status` | Handlingens lifecycle-status |
| `depends_on_action_id` | Eventuel handling, der skal afsluttes først |
| `result_json` | Det strukturerede resultat |
| `created_at` | Oprettelsestidspunkt |
| `completed_at` | Afslutningstidspunkt |

Orchestrator-tabellerne bruger statusværdierne `pending`, `routed`, `in_progress`, `blocked`, `completed`, `failed` og `cancelled`.

### `search_console_properties`

Indeholder de Search Console-properties, som den godkendte Google-konto har read-only-adgang til.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `site_url` | Search Console-property URL og unik nøgle |
| `permission_level` | Kontoens tilladelsesniveau |
| `website_id` | Eventuelt matchet domæne fra Website Registry |
| `active` | Om property-posten er aktiv |
| `created_at` | Første registreringstidspunkt |
| `updated_at` | Seneste synkroniseringstidspunkt |

Properties uden domænematch bevares med tom `website_id`. Gentagne synkroniseringer opdaterer den eksisterende post ud fra `site_url` og opretter ikke dubletter.

### `search_console_daily_metrics`

Indeholder samlede dagstal fra Search Analytics API for matchede websites.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `website_id` | Matchet domæne fra Website Registry |
| `site_url` | Den anvendte Search Console-property |
| `metric_date` | Kalenderdatoen for målingen |
| `clicks` | Samlet antal klik |
| `impressions` | Samlet antal visninger |
| `ctr` | Klikrate som decimaltal |
| `average_position` | Gennemsnitlig placering |
| `created_at` | Første importtidspunkt |
| `updated_at` | Seneste importtidspunkt |

Kombinationen af `website_id` og `metric_date` er unik. En gentagen import opdaterer derfor det eksisterende dagspunkt, også hvis property-URL eller måleværdier er ændret.

### `seo_health_history`

Indeholder deterministiske SEO Health-snapshots for 7, 28 og 90 dage sammenlignet med den foregående periode af samme længde.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `website_id` | Website fra Website Registry |
| `date` | Analysedato |
| `period` | Perioden `7d`, `28d` eller `90d` |
| `score` | SEO-score fra 0 til 100 |
| `trend` | `growing`, `stable`, `declining` eller `critical` |
| `click_change` | Procentvis ændring i klik |
| `impression_change` | Procentvis ændring i visninger |
| `ctr_change` | Ændring i CTR målt i procentpoint |
| `position_change` | Forskel i vægtet gennemsnitsplacering |
| `created_at` | Første analysetidspunkt |
| `updated_at` | Seneste analysetidspunkt |

Kombinationen af `website_id`, `date` og `period` er unik. Gentagen analyse samme dag opdaterer derfor snapshot-resultatet uden dubletter.

### `seo_recommendations`

Indeholder SEO Managers daglige analysebeslutning og koblingen til et eventuelt recovery-projekt.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `website_id` | Website fra Website Registry |
| `analysis_date` | Dato for agentanalysen |
| `seo_score` | Den anvendte 28-dages SEO-score |
| `trend` | Den dokumenterede SEO-trend |
| `reason` | Databaseret begrundelse |
| `recommendation` | Anbefalet næste handling |
| `priority` | `critical`, `high`, `medium` eller `low` |
| `project_id` | Eventuelt SEO Recovery-projekt |
| `status` | `no_action`, `project_created` eller `project_updated` |
| `created_at` | Første analysetidspunkt |
| `updated_at` | Seneste analysetidspunkt |

Kombinationen af `website_id` og `analysis_date` er unik. En gentagen agentkørsel samme dag opdaterer anbefalingen uden dublet.

### Udvidelse af `tasks`

Opgaver har feltet `measurement_method`, som beskriver den konkrete metode til at kontrollere opgavens resultat. Eksisterende databaser migreres automatisk med en tom standardværdi.

### `website_profiles`

Aktuel samlet profil pr. website med CMS, tema, monetization, niche, website health, stærke/svage områder og gemte anbefalinger. `website_id` er unik.

### `website_statistics`

Dagligt snapshot med Search Console-totaler, Partner Ads-salg/provision, SEO Health og antal aktive projekter/opgaver. Kombinationen af `website_id` og `statistic_date` er unik.

### `website_categories`

Rangerede niche- og monetization-kategorier pr. website. Kombinationen af website, kategori og kategoritype er unik.

### `website_history`

Versionerede profilsnapshots med listen over ændrede topniveau-felter. Kombinationen af `website_id` og `history_date` er unik, og uændrede gentagelser opretter ingen række.

### `measurements`

Indeholder målinger af effekten før og efter udførte opgaver.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `task_id` | Reference til den målte opgave |
| `metric` | Navnet på den målte metrik |
| `value_before` | Værdi før ændringen |
| `value_after` | Værdi efter ændringen |
| `measurement_date` | Datoen for målingen |
| `conclusion` | Konklusion på den målte effekt |

### `recommendations`

Indeholder anbefalinger fra systemets AI-medarbejdere.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `agent` | AI-medarbejderen eller agenten bag anbefalingen |
| `website_id` | Reference til det relevante website |
| `recommendation` | Selve anbefalingen |
| `evidence` | Data eller argumentation, der understøtter anbefalingen |
| `priority_score` | Beregnet prioritet |
| `status` | Anbefalingens aktuelle status |
| `created_at` | Tidspunktet, hvor anbefalingen blev oprettet |

## Migration til Supabase

SQLite bruges under udviklingen, fordi databasen er enkel at drive lokalt og ikke kræver en separat databaseserver. Når datastrukturen er stabil, og SU Media AI Office skal køre døgnet rundt, migreres data og tabeller til Supabase PostgreSQL.

Migrationen skal bevare unikke ID'er, relationer, datatyper og historiske data. Applikationens databaseadgang bør holdes adskilt fra forretningslogikken, så skiftet fra SQLite til PostgreSQL kræver så få ændringer som muligt.

## Åbne beslutninger

- Hvor programmet og den fremtidige database skal køre 24/7.
- Hvornår datastrukturen er stabil nok til migration til Supabase.
- Hvordan backup, gendannelse og opbevaringsperioder skal håndteres.
- Hvilke adgangsregler og rettigheder de forskellige AI-medarbejdere skal have.
