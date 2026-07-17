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

### `tasks`

Indeholder konkrete arbejdsopgaver, som systemet eller en AI-medarbejder har identificeret.

| Felt | Beskrivelse |
| --- | --- |
| `id` | Intern unik identifikator |
| `website_id` | Reference til det website, opgaven vedrører |
| `title` | Kort titel |
| `description` | Beskrivelse af opgaven |
| `reason` | Begrundelse for, at opgaven bør udføres |
| `data_source` | Datakilden bag opgaven |
| `expected_minutes` | Forventet tidsforbrug i minutter |
| `expected_effect` | Forventet effekt |
| `priority_score` | Beregnet prioritet |
| `status` | Opgavens aktuelle status |
| `created_at` | Tidspunktet, hvor opgaven blev oprettet |
| `completed_at` | Tidspunktet, hvor opgaven blev afsluttet |

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
