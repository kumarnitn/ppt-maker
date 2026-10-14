# PPT Master & Standalone PPT Maker — Repository Analysis

## 1. Executive Summary

This repository contains two distinct architectural layers:
1. **The Original PPT Master Skill & Script Engine** (`skills/ppt-master/`): A comprehensive, agent-driven tool suite for turning diverse source documents into high-quality, natively editable DrawingML `.pptx` decks with SVG authoring, rigorous multi-stage quality gates, vector icon syncing, AI image generation, chart recall, slide transitions, animation triggers, and TTS audio narration.
2. **The Standalone Application Scaffold** (`app/`, `frontend/`, `docs/standalone-architecture-guide.md`): A Python Flask web server, REST API, SQLite-based job store, and modern web UI that wraps PPT Master's scripts into an autonomous pipeline powered by direct LLM API calls (Azure OpenAI, OpenAI) and image generation APIs (Flux 2 Pro MaaS / Azure AI Studio, Gemini / Nano Banana, local).

This document provides a comprehensive audit of both codebases, their entry points, data flows, script invocations, external dependencies, and gap analysis against the 65 capabilities requested in the Master Implementation Prompt.

---

## 2. Inventory of Current Application Architecture

### 2.1 Entry Points
* **CLI Entry Point**: `app/main.py generate [OPTIONS] [SOURCE_FILE]` — Invokes the deterministic workflow engine from the terminal.
* **Web Server Entry Point**: `app/main.py server [--port PORT] [--host HOST]` — Starts the Flask web server hosting both the REST API and the frontend single-page application.
* **REST API Blueprint**: `app/api/` (`routes.py`, `jobs.py`, `downloads.py`)
  * `POST /api/jobs` — Uploads source document, parses generation options, initializes project workspace, starts background workflow execution.
  * `GET /api/jobs` & `GET /api/jobs/<job_id>` — Polls job state, progress percentage, phase, logs, and validation summary.
  * `GET /api/jobs/<job_id>/slides` & `GET /api/jobs/<job_id>/slides/<index>` — Delivers SVG slides with dynamic Base64-inlined images for browser preview.
  * `GET /api/jobs/<job_id>/plan` & `POST /api/jobs/<job_id>/approve` — Inspects and approves generated slide plans when review gate is active.
  * `POST /api/jobs/<job_id>/resume` — Resumes interrupted jobs from the latest SQLite checkpoint.
  * `GET /api/downloads/<job_id>/pptx` — Downloads compiled `.pptx` presentations.
* **Web UI Frontend**: `frontend/index.html`, `frontend/style.css`, `frontend/app.js` — Glassmorphism single-page application supporting document upload, style selection, AI provider configuration, dynamic motion toggles, live execution logs, slide thumbnail previews, and fullscreen modal review.

### 2.2 Core Modules in `app/`
* `app/config.py`: Environment configuration via `.env`, dataclass `AppConfig`, validation routines for Azure OpenAI, OpenAI, Flux 2 Pro, and Nano Banana.
* `app/schemas/`: Pydantic V2 models for `JobCreateRequest`, `JobResponse`, `PresentationPlan`, `SlidePlan`, `DesignSpecSchema`, `SpecLockSchema`.
* `app/ai/`:
  * `client.py`: `AzureOpenAIClient`, `OpenAIClient`, `MockAIClient` with structured output parsing and retry loops.
  * `image_provider.py`: `FluxImageProvider` (supporting Azure AI Studio MaaS `FLUX.2-pro` and direct BFL), `NanoBananaImageProvider`, `LocalVectorImageProvider`.
  * `prompts.py`: Planning, design spec, slide generation, and targeted repair prompts with real-world executive consulting templates (Hero Split, Multi-Pillar Contrast, Photo Grid, Outlined Feature Cards).
  * `structured_output.py`: Robust JSON extractor handling raw responses, code blocks, and markdown wrappers.
* `app/orchestration/`:
  * `state.py`: Thread-safe SQLite store (`JobStore`) recording jobs, phase transitions, checkpoints, and execution step logs.
  * `workflow.py`: Deterministic state machine executing Phase 0 (Intake) → Phase 1 (Planning) → Phase 2 (Design) → Phase 3 (Construction & Quality Gates) → Phase 4 (Speaker Notes) → Phase 5 (Compilation & Export).
  * `checkpoints.py` & `recovery.py`: Job checkpoint recording and resumption logic.
* `app/services/`:
  * `document_service.py`: Wraps `source_to_md.py` for multi-format document conversion.
  * `project_service.py`: Wraps `project_manager.py` for project workspace directory creation.
  * `planning_service.py`: Orchestrates AI analysis to produce `presentation_plan.json`, `design_spec.md`, and `spec_lock.md`.
  * `asset_service.py`: Manages `icon_sync.py`, contextual AI image acquisition, and `analyze_images.py`.
  * `slide_service.py`: Sequential slide SVG generation with early preflight and targeted repair.
  * `notes_service.py`: Speaker notes generation and synchronization with `total_md_split.py`.
  * `validation_service.py`: Wraps `svg_quality_checker.py` and applies text overflow preflight and SVG sanitation.
  * `export_service.py`: Wraps `finalize_svg.py` and `svg_to_pptx.py` with native PowerPoint transitions and dynamic animations.

---

## 3. Original PPT Master Reusable Tool Suite Audit

The `skills/ppt-master/scripts/` directory contains rich, battle-tested Python utilities designed for PowerPoint generation:

| Script / Directory | Primary Role | Inputs | Outputs | Standalone Reusability |
| :--- | :--- | :--- | :--- | :--- |
| `source_to_md.py` & `source_to_md/` | Converts PDF, DOCX, PPTX, XLSX, HTML, Web URLs to normalized Markdown. | Raw file or URL | `sources/*.md` | **High** — Fully wrapped in `DocumentService`. Supports OCR and table preservation. |
| `project_manager.py` | Initializes project directory layout, manages locks, validates sources. | Project slug, canvas format | `projects/<slug>/` scaffold | **High** — Fully wrapped in `ProjectService`. |
| `icon_sync.py` | Synchronizes vector icons from `templates/icons/` into project `icons/`. | Project path, icon names | `icons/*.svg` | **High** — Reused in `AssetService`. |
| `image_search.py` | Dispatches image search queries to Bing / Unsplash / Google. | Query, output path | Search result images | **Medium** — Needs direct adapter integration in standalone app. |
| `image_gen.py` & `image_backends/` | AI image generation supporting 15 backends (BFL, OpenAI, Gemini, Replicate, Fal, etc.). | `image_prompts.json` manifest | `images/*.png` | **High** — Integrated via `FluxImageProvider` and manifest processor. |
| `analyze_images.py` | Extracts image aspect ratios, dimensions, color tones for layout binding. | `images/` directory | Analysis metadata | **High** — Reused in `AssetService`. |
| `chart_recall.py` | Injects data-backed native PowerPoint charts into SVG authoring. | Data table, chart type | DrawingML chart spec | **Medium** — Needs layout integration in `SlideService`. |
| `visualization_recall.py` | Generates structured diagrams (process, timeline, matrix). | Relationship topology | Diagram SVG components | **Medium** — Can be wired into layout prompts and templates. |
| `pptx_animations.py` & `animation_config.py` | Maps top-level `<g id="...">` elements to 232 native PowerPoint animation keys. | `svg_output/`, animation rules | `animations.json` sidecar | **High** — Directly supported via `svg_to_pptx.py -a auto`. |
| `pptx_transitions.py` | Applies 48 PowerPoint native transitions (push, fade, wipe, reveal, morph). | Transition effect name | PPTX `<p:transition>` tags | **High** — Directly supported via `svg_to_pptx.py -t <effect>`. |
| `notes_to_audio.py` & `tts_backends/` | Converts slide speaker notes into spoken audio voiceover (Edge TTS, ElevenLabs, etc.) with word timings. | `notes/*.md` | `audio/*.m4a`, `audio/*.srt` | **High** — Can be integrated as optional audio narration phase. |
| `svg_quality_checker.py` | Evaluates SVGs against 40+ rules: boundary, viewBox, overflow, font sizes, colors, banned tags. | `svg_output/` | Quality reports (JSON/stdout) | **High** — Reused in `ValidationService` and `SlideService`. |
| `finalize_svg.py` & `svg_finalize/` | Resolves image paths, embeds icons, flattens tspans, validates coordinates. | `svg_output/` | `svg_final/` | **High** — Reused in `ExportService`. |
| `svg_to_pptx.py` & `svg_to_pptx/` | Compiles SVG slides and assets into native DrawingML `.pptx` presentation. | `svg_output/`, assets | `exports/*.pptx` | **Core** — Reused in `ExportService`. |
| `pptx_opc_validation.py` | Validates OpenXML package structure, parts, and integrity. | `*.pptx` file | Package validation status | **High** — Can be added as Layer 3 QA check. |
| `pptx_to_svg.py` & `pptx_template_import.py` | Imports existing `.pptx` decks into editable SVG workspaces for beautification/roundtrip. | `*.pptx` file | Workspace with SVGs | **High** — Foundation for PPTX Import & Beautify workflows. |

---

## 4. Gap Analysis Against Master Requirements

1. **Document Ingestion**: Multi-format conversion is working via `source_to_md.py`. OCR for scanned documents needs explicit verification of system dependencies (`tesseract` / `pdf2image`).
2. **Visual Engine & Templates**: Templates have been upgraded with Executive Consulting layouts (`hero_split_image`, `executive_pillars`, `photo_cards_grid`, `icon_feature_cards`, `matrix_grid_2x4`). Native charts (`chart_recall.py`) and complex topology diagrams (`visualization_recall.py`) need explicit wiring.
3. **Quality & Validation**: Early preflight and final `svg_quality_checker.py` are active. Package-level validation (`pptx_opc_validation.py`) and rasterized visual inspection (`qlmanage` / headless Chrome / Pillow) can be added as Layer 3 and Layer 4 checks.
4. **Dynamic Capabilities**: PowerPoint transitions (`-t push`) and object animations (`-a auto`) are now enabled. Audio narration via `notes_to_audio.py` (Edge-TTS) can be exposed as an optional toggle.
5. **Advanced Workflows**: Existing PPTX import (`pptx_to_svg.py`) and presentation beautification (`beautify_identity.py`) are present in PPT Master scripts and can be exposed as distinct API routes and workflow options.
