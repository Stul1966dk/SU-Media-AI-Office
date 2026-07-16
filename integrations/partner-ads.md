# Partner-ads-integration

## Formål

Hent salgsdata fra Partner-ads, validér dem og aflever nye, normaliserede salg til systemets lager og Notification Service.

## Version 0.1

Integrationen skal:

- hente XML-feedet hvert 30. minut,
- læse relevante salgsfelter,
- identificere hvert salg entydigt,
- undgå at registrere samme salg flere gange,
- gemme nye salg,
- beregne dagens samlede provision,
- rapportere fejl uden at lække feedadresse eller nøgle.

## Forventede notifikationsfelter

- tidspunkt,
- program eller annoncør,
- website,
- ordrebeløb,
- provision,
- samlet provision i dag.

De præcise feltnavne og datatyper dokumenteres, når et sikkert eksempel på feedets struktur er analyseret.

## Afgrænsning

Integrationen fortolker ikke forretningsudviklingen og giver ikke strategiske råd. Den leverer korrekte og sporbare data.

## Sikkerhed

Feedadresse og adgangsoplysninger må ikke gemmes i dette dokument eller i versionsstyret kode.
