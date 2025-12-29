---
title: Ordinal
description: "A boundless engine for structured thought and other pretentiousness"
division: ["Code"]
domain: "Development"
worked: 8.5
created: 2025-01-30 11:49:56
last_modified: 2025-11-16 12:52:12
template: "wiki.html"
---

## Ordinal
![Ordinal's Icon](../images/512ordinal.png)
This page is an early draft. More details about its architecture, features, and implementation will be added over time.

Ordinal is a static site generator. It is written in Python and generates a structured, interlinked wiki from Markdown with little dependencies.

The generator handles wikilinks, backlinks, frontmatter metadata, and template-driven rendering, ensuring that every document is self-contained and properly linked. Markdown files are automatically converted into structured HTML pages, while the directory layout is preserved in the output.

Ordinal enforces link correctness, resolving all internal references at build time. Broken links are automatically detected and resolved, with missing pages generated as placeholders. The system tracks backlinks dynamically, ensuring that referenced pages always display their incoming links.

