---
title: "Specifikáció: Wise Banki Mikorszerviz"
description: "Wise bankkivonat letöltés és szinkronizálás az szamla-db rendszerrel"
language: "HU"
last_updated: "2026-06-10"
related: [INDEX.md, szamla-db-spec.md, wise-spec.md]
---

# Wise Banki Mikorszerviz - Prompt

Implementálni egy robusztus, Python-alapú microservicot használatával, amely automatizálja a Wise banki kivonatai letöltését, és szinkronizálja a tranzakciós adatokat a meglévő `szamla-db` ökoszisztémával.
A szolgáltatáshoz készüljön cli és fastapi rest interface.

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[wise-spec.md|Wise Integráció Spec]]
- **Cél adatbázis**: [[szamla-db-prompt.md|Szamla-DB Prompt]] → [[szamla-db-spec.md|Szamla-DB Spec]] (közvetlen PostgreSQL írás)
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]