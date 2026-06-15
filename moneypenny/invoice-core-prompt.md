---
title: "Prompt: Számla Adatbázis Mikroszerviz"
language: "HU"
related: [invoice-core-spec.md, nav-számla-prompt.md]
---

Készüljön egy mikroservice ami a nav-invoice meghívásával adatbázisba menti a számlákat, létrehozza a vevői és szállítói táblákat a nav-invoice adatok alapján.
A invoice-file-filter szolgáltatás meghívásával adatbázisba menti a pdf-számlákat és a invoice-file-filter  words segítségével (nav-invoice számlaszám alapján megkersi melyik pdf file tartalmazza words) összeköti nav-számla táblával a számla meta-adatai alapján.
A invoice-file-filter szolgáltatás által visszaadott adatok kerüljenek egy külön táblába és legyenek összekötve a invoice-core megfelelő tábláival.
A wise szolgáltatás meghívásával lekéri a pénzügyi tranzakciókat ezeket táblába menti és összeköti a invoice-core megfelelő tábláival.
A szolgáltatáshoz készüljön cli és fastapi rest interface.

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[invoice-core-spec.md|Invoice-Core Spec]]
- **Meghívja**: [[nav-számla-prompt.md|NAV Számla Prompt]] → [[nav-invoice-spec.md|NAV Számla Spec]]
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]

