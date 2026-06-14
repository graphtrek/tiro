---
title: "Prompt: Gmail PDF Letöltő"
language: "HU"
related: [attachment-downloader-spec.md, pdf-szamla-prompt.md]
---

Készítsünk egy mikroservice-t, ami le tudja tölteni az email pdf csatolmányokat a gmail levelekből, időintervallum alapján pl from: 2026-05-01 to 2026-05-31 
a letöltött pdf fájlokat mentse le és a file nevek legyenek prefix-el ellátva
pl.: 2026-05-001_filename. A szolgáltatáshoz készüljön cli és fastapi rest interface

---

## 🔗 Wiki Linkek
- **Specifikáció**: [[attachment-downloader-spec.md|Graphtrek Email Spec]]
- **Meghívva**: [[pdf-szamla-prompt.md|PDF Szamla Prompt]] → [[pdf-szamla-spec.md|PDF Szamla Spec]]
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
- **Hívási lánc végpontja**: Nincs outgoing API hívása
