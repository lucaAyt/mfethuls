# Roadmap

This file pins the current top-level objectives for mfethuls. The intent is to keep development focused on the linear path from raw instrument data to normalized, reusable datasets, before polishing UX and maintenance details.

## 1. Core Pipeline

- Registry row -> parser -> schema normalization -> Dataset -> storage
- Keep the user-facing workflow simple and predictable
- Preserve raw data provenance in metadata

## 2. Storage and Database

- Use local parquet/JSON as the first cache layer
- Keep the storage interface pluggable so a database backend can be added later
- Make the Dataset abstraction the stable contract across backends

## 3. Canonical Plotting

- Build plotting helpers only on normalized columns
- Prefer instrument-family plotting helpers over raw-export-specific code
- Keep plots aligned with canonical schema names and units

## 4. Clean-up and Polish

- Reduce parser wrapper duplication
- Add a registry validator
- Write a short profile setup guide
- Document how new instruments are onboarded

## Ownership Split

- Code maintainers own new instrument support, parser changes, schema files, and core backend behavior
- Researchers own experiment registry entries, descriptions, and profile selection within the approved schema contract
