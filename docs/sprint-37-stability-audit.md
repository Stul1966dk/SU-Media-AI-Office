# Sprint 37 – Stabilitetsaudit

## Omfang

Sprintet gennemgår det eksisterende flow fra Search Console-kandidat til
afsluttet SEO-eksperiment. Der er ikke tilføjet automatiske websiteændringer
eller nye AI-moduler.

## Auditværktøj

Den rapporterende kontrol ændrer aldrig data:

```powershell
python scripts/audit_system.py
```

Sikre, ikke-slettende reparationer skal vælges eksplicit:

```powershell
python scripts/audit_system.py --repair-safe
```

Repair-funktionen ruller falske godkendelser tilbage og markerer ufuldstændige
Approved Changes som `Kræver gennemgang`. Usikre relationer gættes ikke.

## Fund og årsager

### Kritisk

- En arbejdskøpost kunne historisk markeres som godkendt uden en Title
  Optimization-kladde. Det generiske godkendelsesflow oprettede projekt,
  opgave og eksperiment uden valgte tekster.
- Godkendte tekster fandtes tidligere flere steder. `approved_changes` er nu
  den permanente og autoritative datakilde for Dagens arbejde.

### Høj

- Gentaget godkendelse og implementering gav fejl i stedet for at returnere
  det allerede oprettede resultat. Handlingerne er nu idempotente.
- Statusovergange var spredt som frie tekstværdier. De lovlige overgange er nu
  samlet i `core/workflow_status.py`.

### Middel

- Title optimering viste den interne status `awaiting_approval`.
- Website Profile kunne vise interne statusværdier direkte.

Begge visninger bruger nu fælles danske statusnavne.

### Lav

- Streamlit kræver procesgenstart, når allerede importerede Python-moduler
  ændres. Dashboardet er genstartet og genkontrolleret.

## Databasekontrol

Auditen kontrollerer blandt andet:

- godkendte køopgaver uden Approved Change;
- obligatoriske felter i Approved Change;
- aktive eksperimenter uden baseline eller URL-lås;
- manglende projekt- og opgavereferencer;
- projekter uden opgaver;
- dublerede aktive køelementer, opgaver og baselines;
- uoverensstemmende status mellem kø, Approved Change og eksperiment;
- titlekladder, som låser en URL uden aktivt eksperiment.

Den aktuelle database gav efter sikker migrering:

```text
finding_count: 0
```

## Test og manuel kontrol

- Baseline før Sprint 37: 121 tests.
- Nye tests dækker statusovergange, falsk godkendelse, sikker repair samt
  dobbelt godkendelse og dobbelt implementering.
- 18 dashboardsider er gennemgået i browseren.
- Dagens arbejde, Title optimering og SEO er kontrolleret ved 640 px uden
  horisontalt overflow.
- Manuel implementering mod et website blev ikke udført. Knappen må kun bruges,
  efter at den viste ændring faktisk er publiceret manuelt.

## Kendte begrænsninger

- URL-lås er afledt af eksperiment-, kladde- og observationsstatus; den findes
  ikke som en selvstændig låsetabel.
- Historiske records uden dokumenterbare tekster markeres til gennemgang.
  Systemet gætter aldrig en title eller metabeskrivelse.
- Streamlits HTML-komponent til kopier-knapper udløser en upstream
  deprecation-advarsel i tests, men fungerer fortsat i den aktuelle UI.
