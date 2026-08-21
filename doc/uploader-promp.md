---
title: "Uploader – Bankkivonat Feltöltő Szolgáltatás"
description: "Bankkivonat fájlok (Erste/Wise CSV) feltöltése storage folderbe; UI a vision-ben, backend neve uploader"
type: "service-prompt"
status: "tervezett"
port: 8006
language: "HU"
last_updated: "2026-06-24"
depends_on: [bank-spec.md, vision-spec.md]
related: [INDEX.md, bank-spec.md, bank-prompt.md, vision-spec.md, vision-prompt.md]
tags: [uploader, bank, erste, wise, csv, storage, fastapi, vision]
---

Szeretném a bank tranzakciókat feltölteni a storage folder be. Készíts hozzá egy szolgáltatást a ui legyen a vision szolgáktatásban a backend neve legyen uploader.

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[uploader-spec.md|Uploader Spec]]
- **UI**: [[vision-spec.md|Vision Spec]] → [[vision-prompt.md|Vision Prompt]] (a feltöltési felület a vision-ban van)
- **Célmappa fogyasztója**: [[bank-spec.md|Bank Spec]] → [[bank-prompt.md|Bank Prompt]] (a feltöltött CSV fájlokat a bank szolgáltatás dolgozza fel)
- **Projekt Index**: [[INDEX.md|Tiro Index]]
