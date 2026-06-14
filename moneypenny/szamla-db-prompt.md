---
title: "Prompt: Számla Adatbázis Mikroszerviz"
language: "HU"
related: [szamla-db-spec.md, nav-számla-prompt.md]
---

Készüljön egy mikroservice ami a nav-szamla meghívásával adatbázisba menti a számlákat, létrehozza a vevői és szállítói táblákat a nav-szamla adatok alapján.
A pdf-szamla szolgáltatás meghívásával adatbázisba menti a pdf-számlákat és a pdf-szamla  words segítségével (nav-szamla számlaszám alapján megkersi melyik pdf file tartalmazza words) összeköti nav-számla táblával a számla meta-adatai alapján.
A pdf-szamla szolgáltatás által visszaadott adatok kerüljenek egy külön táblába és legyenek összekötve a szamla-db megfelelő tábláival.
A szolgáltatáshoz készüljön cli és fastapi rest interface.

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[szamla-db-spec.md|Szamla-DB Spec]]
- **Meghívja**: [[nav-számla-prompt.md|NAV Számla Prompt]] → [[nav-szamla-spec.md|NAV Számla Spec]]
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]

