---
title: "Prompt: Gmail PDF Letöltő"
language: "HU"
related: [attachment-downloader-spec.md, invoice-file-filter-prompt.md]
---

Készítsünk egy mikroservice-t, ami le tudja tölteni az email pdf csatolmányokat a gmail levelekből, időintervallum alapján pl from: 2026-05-01 to 2026-05-31 
a letöltött pdf fájlokat mentse le és a file nevek legyenek prefix-el ellátva
pl.: 2026-05-001_filename. A szolgáltatáshoz készüljön cli és fastapi rest interface

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[attachment-downloader-spec.md|Attachment Downloader Spec]]
- **Meghívva**: [[invoice-file-filter-prompt.md|PDF Feldolgozó Prompt]] → [[invoice-file-filter-spec.md|PDF Feldolgozó Spec]]
- **Projekt Index**: [[INDEX.md|Tiro Index]]
- **Hívási lánc végpontja**: Nincs outgoing API hívása
