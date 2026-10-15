# Pipeline Architecture & Module Collaboration Guide

This document provides a comprehensive, deep-dive explanation of how modules, services, AI providers, and underlying script tools collaborate in the **PPT Master Standalone Application** to transform raw source documents into fully styled, editable, animated PowerPoint presentations (`.pptx`).

---

## 1. Executive Summary & Core Architectural Principle

The application operates as an **autonomous, deterministic orchestration pipeline**. It takes unformatted documents (PDF, Word DOCX, Markdown, Text, HTML), analyzes their substance using AI models, synthesizes a high-density presentation plan, authors pixel-perfect DrawingML-compatible SVG slides, validates them against rigorous publication quality gates, and compiles them into native PowerPoint presentations.

### The Core Architectural Invariant
Unlike agentic systems that rely on conversational loops (such as Cursor or Claude Code), this application runs **100% deterministically as standard Python application code**:
- External AI models (Azure OpenAI, OpenAI, Azure AI Studio Flux 2 Pro) are treated as **stateless functional APIs**.
- State transitions, error handling, filesystem layout, and compilation steps are strictly governed by the **Workflow Engine** (`app/orchestration/workflow.py`).
- No AI model decides control flow or manages tool execution; Python code controls every boundary.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        User Interface & Clients                        │
│             Web UI (frontend/app.js)  |  Headless CLI                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP REST / CLI Invocations
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Flask REST API Gateway                          │
│     app/api/jobs.py  |  app/api/routes.py  |  app/api/downloads.py     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Asynchronous Job Dispatch
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  Workflow Orchestration Engine                         │
│                    app/orchestration/workflow.py                       │
│        Governs state machine, checkpoints, logging, and error recovery │
└──────┬───────────────┬───────────────┬────────────────┬──────────┬─────┘
       │               │               │                │          │
       ▼               ▼               ▼                ▼          ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  Document   │ │ Presentation│ │    Asset    │ │ Slide & SVG │ │  Export &   │
│   Service   │ │  Planning   │ │   Service   │ │   Service   │ │ Quality QA  │
│ (Doc to MD) │ │(Plan & Spec)│ │(Flux & Icons│ │(AI Authoring│ │(Validator & │
│             │ │             │ │ & Manifest) │ │  & Healing) │ │ svg_to_pptx)│
└──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
       │               │               │                │          │
       ▼               ▼               ▼                ▼          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Internal Helpers & Script Toolchain                  │
│   • AI Client & Prompt Blueprints (app/ai/client.py, prompts.py)       │
│   • PPT Master Script Suite (skills/ppt-master/scripts/*)              │
│   • SQLite State Store (app_data/jobs.db)                              │
│   • Project Workspace Tree (projects/<slug>_<timestamp>/)              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. File & Module Directory Map

The table below details every primary file, its architectural responsibility, and the components it collaborates with:

| File Path | Architectural Role | Collaborators & Dependencies |
| :--- | :--- | :--- |
| **`app/main.py`** | Application bootstrap & CLI entrypoint; launches Flask server or CLI runner. | `app/api/*`, `app/config.py`, `app/orchestration/workflow.py` |
| **`frontend/app.js`** | Single-page Web UI application logic; handles upload, polling, approval, preview, and download. | Flask API endpoints (`/api/jobs`, `/api/config`) |
| **`app/api/jobs.py`** | REST endpoints for job creation, progress polling, plan review, and approval. | `JobStore`, `WorkflowEngine` |
| **`app/api/routes.py`** | General API routes (health checks, system configuration, available providers). | `AppConfig` |
| **`app/api/downloads.py`** | Secure file delivery for compiled `.pptx` and exported slide SVG assets. | `JobStore`, filesystem |
| **`app/orchestration/workflow.py`** | **Central Pipeline Conductor**. Orchestrates all 7 execution phases, error tracking, and checkpoints. | All domain services (`app/services/*`), `JobStore` |
| **`app/orchestration/state.py`** | Thread-safe SQLite persistence layer for jobs, progress percentages, and phase logs. | SQLite database (`data/jobs.db`) |
| **`app/services/document_service.py`** | Converts source files (PDF, DOCX, TXT) into normalized Markdown. | `skills/ppt-master/scripts/source_to_md.py` |
| **`app/services/project_service.py`** | Provisions canonical project workspaces, metadata, and source imports. | `skills/ppt-master/scripts/project_manager.py` |
| **`app/services/planning_service.py`** | Analyzes document text and produces structured `PresentationPlan` and `DesignSpecSchema`. | `app/ai/client.py`, `app/ai/prompts.py` |
| **`app/services/asset_service.py`** | Sources visual assets: syncs vector icons and generates AI images via Flux 2 Pro. | `skills/ppt-master/scripts/icon_sync.py`, `app/ai/image_provider.py` |
| **`app/services/slide_service.py`** | Synthesizes SVG slides sequentially, embeds icons/images, and runs healing loops. | `app/ai/client.py`, `ValidationService`, `skills/ppt-master/scripts/` |
| **`app/services/validation_service.py`** | Multi-layer SVG QA: sanitizes XML entities, escapes `&`, clamps coordinates, checks gates. | `skills/ppt-master/scripts/svg_quality_checker.py` |
| **`app/services/notes_service.py`** | Generates executive speaker talking points and splits them into slide-specific Markdown. | `app/ai/client.py`, `skills/ppt-master/scripts/total_md_split.py` |
| **`app/services/export_service.py`** | Finalizes placeholders and compiles SVGs into DrawingML `.pptx` with native animations. | `skills/ppt-master/scripts/finalize_svg.py`, `svg_to_pptx.py` |
| **`app/ai/client.py`** | Unified LLM abstraction (Azure OpenAI / OpenAI); handles structured JSON parsing and prompts. | `app/ai/prompts.py`, `app/ai/structured_output.py` |
| **`app/ai/prompts.py`** | System and user prompts, layout blueprints, animation container rules, and leakage guards. | `app/ai/client.py` |
| **`app/ai/image_provider.py`** | Flux 2 Pro generation over Azure AI Studio MaaS or BFL API with high-res PIL fallback. | Azure AI Studio REST endpoint |

---

## 3. End-to-End Execution Trace: From Document to PPTX

The presentation generation pipeline progresses through **seven deterministic phases**. Below is the exact step-by-step sequence of how data and control pass between files.

```
       DOCUMENT UPLOAD (PDF / DOCX)
                  │
                  ▼
   [Phase 1: Ingestion & Workspace Setup]
                  │
                  ▼
      [Phase 2: Narrative Planning]
                  │
        (User Approval Gate?)
         ├── Yes ──► [Wait for Review] ──► [Plan Approved]
         └── No (Auto) ──────────────────────────┘
                  │
                  ▼
      [Phase 3: Design Spec & Asset Prep]
                  │
                  ▼
   [Phase 4: Slide SVG Authoring & Healing]
                  │
                  ▼
       [Phase 5: Early Quality Gate]
                  │
                  ▼
    [Phase 6: Final Gate & Speaker Notes]
                  │
                  ▼
  [Phase 7: Asset Finalization & PPTX Compilation]
                  │
                  ▼
        DELIVERABLE (.pptx)
```

---

### Phase 1: Intake, Conversion & Workspace Provisioning

1. **User Request**:
   - The user submits a file (e.g., `SGH_Proposal.pdf`) via the Web UI (`frontend/app.js` -> `POST /api/jobs`) or CLI (`app/main.py cli`).
   - `app/api/jobs.py` stores the uploaded file in `data/uploads/` and inserts an initial record with status `QUEUED` into SQLite (`app/orchestration/state.py`).
2. **Background Thread Launch**:
   - A background thread spawns `WorkflowEngine.run_job(job_id)`.
3. **Format Normalization** (`app/services/document_service.py`):
   - Invokes `skills/ppt-master/scripts/source_to_md.py` via Python subprocess.
   - Converts PDF text, tables, and section headings into a unified, clean Markdown document (`data/uploads/<job_id>_<name>.md`).
4. **Project Workspace Provisioning** (`app/services/project_service.py`):
   - Executes `skills/ppt-master/scripts/project_manager.py init <slug> --quick-generate`.
   - Creates a isolated directory structure under `projects/<slug>_<timestamp>/`:
     ```
     projects/<slug>_<timestamp>/
     ├── sources/             # Raw source PDF & converted Markdown
     ├── images/              # AI-generated contextual photography & manifests
     ├── icons/               # Synchronized vector SVG icons
     ├── svg_output/          # Generated slide SVGs
     ├── svg_final/           # Post-processed SVGs ready for OpenXML packaging
     ├── notes/               # Speaker notes (total.md and per-slide .md)
     ├── validation/          # Quality reports and audit logs
     └── exports/             # Final compiled .pptx presentations
     ```
   - Imports source documents into `sources/` via `project_manager.py import-sources`.

---

### Phase 2: Semantic Analysis & Presentation Planning

1. **Information Extraction** (`app/services/planning_service.py`):
   - Reads the normalized source Markdown.
   - Formulates the prompt using `PLANNING_SYSTEM_PROMPT` and `PLANNING_USER_PROMPT` from `app/ai/prompts.py`.
2. **LLM Strategy Execution** (`app/ai/client.py`):
   - Sends the payload to Azure OpenAI (`gpt-4o` or `gpt-4o-mini`).
   - The prompt enforces:
     - **High Factual Density**: Extracts exact quantitative figures, dates, institutional convictions, and regulatory standards.
     - **Layout Diversity**: Prohibits using the same layout archetype on adjacent slides.
     - **Multi-tiered Content**: Formats points with Sub-headings, Narrative lines, Bullets, and Summary Tags.
     - **Image Need Assessment**: Identifies which 2–3 slides benefit from photographic illustrations (e.g., Cover, Concept, Site Planning).
3. **Schema Validation & Storage** (`app/schemas/plan.py`):
   - Output JSON is parsed and strictly validated against Pydantic model `PresentationPlan`.
   - Written to `projects/<project>/presentation_plan.json`.
4. **Interactive Approval Gate (Optional)**:
   - If `auto_approve=False`: The job status shifts to `AWAITING_APPROVAL`. The Web UI displays the interactive storyboard modal (`frontend/app.js`), allowing the user to review, edit titles, or modify bullet points before proceeding.
   - If `auto_approve=True`: The engine advances immediately.

---

### Phase 3: Design Specification & Asset Sourcing

1. **Design System Materialization** (`app/services/planning_service.py`):
   - Calls the LLM with `DESIGN_SPEC_SYSTEM_PROMPT` to derive the deck's aesthetic tokens:
     - Default Palette: **Executive Consulting Light** (Pure white background `#FFFFFF`, high-contrast slate text `#0F172A`, cyan `#0284C7`, teal `#0D9488`, and amber `#D97706` accent lines).
     - Typography tokens: 28px slide title, 14px lead subtitle, 12–13px body text.
   - Generates and writes `projects/<project>/design_spec.md` and machine-enforced `spec_lock.md`.
2. **Vector Icon Synchronization** (`app/services/asset_service.py`):
   - Aggregates all `suggested_icons` from each `SlidePlan` (e.g., `tabler-outline/building-hospital`, `tabler-outline/clock`, `tabler-outline/shield-check`).
   - Invokes `skills/ppt-master/scripts/icon_sync.py` to copy vector SVG files from `templates/icons/tabler-outline/` directly into `projects/<project>/icons/tabler-outline/`.
3. **AI Contextual Image Generation** (`app/services/asset_service.py` + `app/ai/image_provider.py`):
   - For every slide with `image_needed=True`:
     - Submits `slide.image_prompt` to **Black Forest Labs Flux 2 Pro** via Azure AI Studio MaaS endpoint (`urllib.request`).
     - Image generation completes in **~8–10 seconds** at 1024x576 resolution (16:9).
     - Saves raw PNGs into `projects/<project>/images/<image_filename>`.
     - Maintains manifest in `images/image_prompts.json` and runs `skills/ppt-master/scripts/analyze_images.py`.
     - *Fallback*: If external AI image generation is disabled or fails, Pillow (`PIL`) generates a crisp, high-resolution vector-styled geometric plate.

---

### Phase 4: Slide SVG Authoring & Self-Healing Loop

Slide authoring is executed slide-by-slide by `app/services/slide_service.py`. For each slide:

1. **Context & Blueprint Assembly** (`app/ai/client.py` + `app/ai/prompts.py`):
   - Pulls layout rules matching `slide.layout_type`:
     - `hero_cover`: Deep navy background `#071426`, technical proposal badge, promise box, and 3 stacked metric cards.
     - `executive_pillars`: 3 crisp white cards with top colored accent lines and deep navy 4-KPI commitment banner.
     - `quadrant_grid`: 4-quadrant challenge/mitigation grid with left vertical color bars and status pill badges.
     - `5_pillar_moves`: 5 slender columns with icons, 2 sub-sections, and bottom pill tags.
     - `hero_split_kpi`: Left navy KPI block or image + right 4 wide stacked horizontal cards.
     - `timeline_phases`: 4 sequential sprint cards with milestone gate pills + bottom governance banner.
   - Embeds available icons and image paths into `SLIDE_SVG_USER_PROMPT`.
2. **Mandatory Dynamic Grouping (`<g id="...">`)**:
   - The prompt instructs the LLM to wrap every visual element into top-level semantic groups in z-order:
     ```xml
     <svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
       <rect id="bg" .../>
       <g id="title-section"> ... </g>
       <g id="card-1"> ... </g>
       <g id="card-2"> ... </g>
       <g id="card-3"> ... </g>
       <g id="kpi-banner"> ... </g>
       <g id="footer-group"> ... </g>
     </svg>
     ```
   - **Why this matters**: In PPT Master's OpenXML compiler (`svg_to_pptx.py`), per-element animations (`-a auto`) attach exclusively to top-level `<g id="...">` containers. Without these groups, PowerPoint renders static slides. With them, cards cascade dynamically.
3. **Multi-Stage Sanitization Engine** (`app/services/validation_service.py`):
   Before the raw SVG is saved or checked, `sanitize_svg_content()` performs deterministic regex cleaning:
   - **Strips Banned Elements**: Removes `<style>`, `<foreignObject>`, `class="..."`, and scripts.
   - **Entity Normalization**: Replaces forbidden HTML entities (`&bull;`, `&mdash;`, `&nbsp;`) with XML Unicode equivalents.
   - **Ampersand & Bracket Escaping**: Converts bare `&` (`Concept & Schematic`, `C&S`, `M&E`) into `&amp;` and stray comparison brackets (`<2 mins`) into `&lt;`.
   - **Auto-Merging Text Nodes**: Detects adjacent `<text>` elements where the second lacks `x`/`y` coordinates and merges them into `<tspan>` children so text never defaults to `y=0` (which triggers off-canvas vertical overflow).
   - **Anti-Leakage Filter**: Strips accidental LLM meta-labels (`Core Message:`, `Visual Direction:`, `© 2023 Company Name`).
   - **Coordinate Clamping**: Clamps element coordinates exceeding the 1280x720 canvas.
4. **Targeted Self-Healing Loop**:
   - `preflight_svg_text()` runs an in-memory XML and boundary check.
   - If syntax or bounding errors are discovered, the faulty SVG is sent to `app/ai/client.py:repair_slide_svg` with the exact compiler errors.
   - Repairs run up to `max_retries_per_slide = 3`. Once verified, the file is atomically written to `svg_output/slide_NN.svg`.

---

### Phase 5: Quality Assurance Gates

The pipeline enforces two fail-closed quality gates using `skills/ppt-master/scripts/svg_quality_checker.py`:

1. **Early Quality Gate (Post-Slide 5)**:
   - Validates that the design language, font definitions, XML syntax, and coordinate boundaries are consistent before authoring the second half of the deck.
   - Command:
     ```bash
     python3 skills/ppt-master/scripts/svg_quality_checker.py projects/<slug> --canonical-authoring --stage early --json --quick-generate
     ```
2. **Final Quality Gate (All Slides)**:
   - Validates the entire deck. Every slide must satisfy:
     - Root canvas viewBox: `0 0 1280 720`.
     - Zero XML parse errors or unescaped tokens.
     - Zero text overflow beyond margins (`x: 60 to 1220`, `y: 40 to 665`).
     - Zero unplaced icon placeholders or missing local image files.
   - Outputs machine-readable report to `validation/svg_quality_final_report.json`.

---

### Phase 6: Executive Speaker Notes Generation

1. **Content Formulation** (`app/services/notes_service.py`):
   - For each slide, sends the slide plan, bullet hierarchy, and visual summary to the LLM using `NOTES_SYSTEM_PROMPT`.
   - Generates articulate spoken remarks, contextual background facts, and narrative transition cues to the next slide.
2. **Notes Splitting**:
   - Consolidates all remarks into `projects/<project>/notes/total.md`.
   - Subprocesses `skills/ppt-master/scripts/total_md_split.py`, which splits the master document into 1:1 slide Markdown files: `notes/slide_01.md`, `notes/slide_02.md`, etc.
   - The OpenXML compiler subsequently reads these files and embeds them natively into PowerPoint presenter notes.

---

### Phase 7: Asset Finalization & Native DrawingML Compilation

1. **Asset Finalization** (`app/services/export_service.py`):
   - Subprocesses `skills/ppt-master/scripts/finalize_svg.py`.
   - Replaces `<use data-icon="tabler-outline/..." .../>` placeholders with inline vector `<path>` definitions from the local `icons/` directory.
   - Writes sanitized, ready-to-compile SVGs into `projects/<project>/svg_final/`.
2. **Native OpenXML PowerPoint Compilation** (`svg_to_pptx.py`):
   - Subprocesses `skills/ppt-master/scripts/svg_to_pptx.py`:
     ```bash
     python3 skills/ppt-master/scripts/svg_to_pptx.py \
       projects/<slug> \
       --quick-generate \
       --with-notes \
       -a auto \
       --animation-trigger after-previous \
       --animation-stagger 0.4 \
       -t push
     ```
   - **DrawingML Translation**: Converts SVG vectors, paths, rects, text nodes, and raster images into 100% native PowerPoint shapes (`p:sp`, `p:pic`, `a:p`, `a:r`).
   - **Dynamic Animations**:
     - Evaluates `<g id="...">` groups.
     - Automatically assigns PowerPoint entrance animations:
       - `id="title-section"` -> `entrance_fade`
       - `id="card-1"`, `id="card-2"`, `id="card-3"` -> `entrance_fly` (cascading stagger)
       - `id="kpi-banner"` -> `entrance_wipe`
     - Applies slide transition: `push` (or user-selected: `fade`, `wipe`, `zoom`).
3. **Validation & Delivery**:
   - `python-pptx` inspects the generated package in `exports/` to verify OpenXML archive integrity and confirm slide counts.
   - Job status is marked as `COMPLETED` (`progress_percent = 100`).
   - The user downloads the presentation via the Web UI button or REST endpoint `GET /api/downloads/<job_id>`.

---

## 4. Architectural Collaboration Diagram

The sequence diagram below illustrates the exact execution and collaboration flow between frontend, API, orchestrator, domain services, AI providers, and low-level scripts:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant WebUI as Frontend (app.js)
    participant API as Flask API (jobs.py)
    participant Engine as WorkflowEngine (workflow.py)
    participant DocSvc as DocumentService
    participant PlanSvc as PlanningService
    participant AssetSvc as AssetService
    participant SlideSvc as SlideService
    participant ValSvc as ValidationService
    participant ExportSvc as ExportService
    participant AI as AI Client (Azure / Flux)
    participant Scripts as PPT Master Scripts

    User->>WebUI: Uploads document & clicks "Generate"
    WebUI->>API: POST /api/jobs (multipart/form-data)
    API->>Engine: Launches background worker run_job(job_id)
    API-->>WebUI: Returns 201 Created (job_id)

    rect rgb(240, 248, 255)
    note over Engine,DocSvc: Phase 1: Ingestion & Normalization
    Engine->>DocSvc: convert_to_markdown(source_file)
    DocSvc->>Scripts: exec source_to_md.py
    Scripts-->>DocSvc: normalized.md
    Engine->>Scripts: exec project_manager.py init <slug>
    end

    rect rgb(245, 255, 245)
    note over Engine,PlanSvc: Phase 2: Narrative Planning
    Engine->>PlanSvc: create_presentation_plan(markdown_text)
    PlanSvc->>AI: generate_plan(PLANNING_PROMPTS)
    AI-->>PlanSvc: JSON outline (10-14 slides)
    PlanSvc-->>Engine: validated PresentationPlan
    end

    rect rgb(255, 250, 240)
    note over Engine,AssetSvc: Phase 3: Design Spec & Asset Prep
    Engine->>PlanSvc: create_design_spec(plan)
    PlanSvc->>AI: generate_spec(DESIGN_SPEC_PROMPTS)
    AI-->>PlanSvc: tokens (Executive Light theme)
    Engine->>AssetSvc: sync_icons(suggested_icons)
    AssetSvc->>Scripts: exec icon_sync.py
    Engine->>AssetSvc: generate_images(slide_image_prompts)
    AssetSvc->>AI: Flux 2 Pro API (Azure AI Studio)
    AI-->>AssetSvc: High-res PNG visuals (slide_NN_hero.png)
    end

    rect rgb(255, 245, 245)
    note over Engine,SlideSvc: Phase 4 & 5: Slide SVG Authoring & Healing
    loop For each slide (1 to N)
        Engine->>SlideSvc: generate_single_slide(slide, spec)
        SlideSvc->>AI: generate_slide_svg(BLUEPRINTS, <g id>)
        AI-->>SlideSvc: raw <svg> markup
        SlideSvc->>ValSvc: sanitize_svg_content(raw)
        ValSvc-->>SlideSvc: cleaned SVG (&amp;, coordinates, tspan)
        SlideSvc->>ValSvc: preflight_svg_text()
        alt If Preflight Issues Detected
            SlideSvc->>AI: repair_slide_svg(errors, svg)
            AI-->>SlideSvc: repaired <svg>
        end
        SlideSvc-->>Engine: saved svg_output/slide_NN.svg
        alt After Slide 5 (Early Gate)
            Engine->>ValSvc: run_quality_checker(--stage early)
            ValSvc->>Scripts: exec svg_quality_checker.py
        end
    end
    end

    rect rgb(245, 245, 255)
    note over Engine,ExportSvc: Phase 6 & 7: Final Gate, Notes & Compilation
    Engine->>ValSvc: run_quality_checker(--stage final)
    ValSvc->>Scripts: exec svg_quality_checker.py
    Engine->>Scripts: generate notes & exec total_md_split.py
    Engine->>ExportSvc: compile_pptx(project_path, animations=True)
    ExportSvc->>Scripts: exec finalize_svg.py (inline vector icons)
    ExportSvc->>Scripts: exec svg_to_pptx.py (-a auto, -t push)
    Scripts-->>ExportSvc: exports/presentation.pptx
    ExportSvc-->>Engine: validated PPTX path
    end

    Engine->>API: Updates job status: COMPLETED
    WebUI->>API: Polls GET /api/jobs/<job_id>
    API-->>WebUI: Status: COMPLETED, download_url: /api/downloads/<job_id>
    WebUI-->>User: Activates "Download PowerPoint (.pptx)"
```

---

## 5. Artifact Transformation Pipeline (Data Flow)

During presentation generation, the source material undergoes five successive transformations across files:

```
[Raw Input Document] (PDF / DOCX / TXT)
  │
  │ Subprocess: source_to_md.py
  ▼
[Normalized Markdown] (sources/<name>.md)
  │
  │ LLM Prompt: PLANNING_SYSTEM_PROMPT
  ▼
[Presentation Plan & Design Spec] (presentation_plan.json, design_spec.md, spec_lock.md)
  │
  │ LLM Prompt: SLIDE_SVG_SYSTEM_PROMPT + Layout Blueprints
  ▼
[Authoring SVGs with <g id> groups] (svg_output/slide_01.svg ... slide_NN.svg)
  │
  │ Deterministic Regex Engine: ValidationService (entity escape, coordinate merge)
  │ Subprocess: finalize_svg.py (vector icon injection)
  ▼
[Finalized DrawingML-Ready SVGs] (svg_final/slide_01.svg ... slide_NN.svg)
  │
  │ Subprocess: svg_to_pptx.py -a auto -t push --with-notes
  ▼
[Native PowerPoint Presentation] (exports/<name>_<timestamp>.pptx)
```

---

## 6. Key Reliability Safeguards & Error Recovery

### 1. Deterministic Sanitization vs. LLM Non-Determinism
LLMs occasionally emit unescaped ampersands (`Concept & Schematic Design`), bare comparison symbols (`<2 mins`), or split `<text>` elements without setting `x` and `y` coordinates on subsequent tags. 
- Rather than relying solely on repetitive LLM repair passes, `app/services/validation_service.py` applies **immediate deterministic regex transformations** to guarantee XML validity:
  - Bare `&` -> `&amp;`
  - Bare `<` before numbers -> `&lt;`
  - Coordinate-less text tags -> auto-merged into `<tspan>` on the preceding tag or anchored to safe canvas baselines.
- This ensures 100% compliance with Python's strict `xml.etree.ElementTree` parser and the publication quality checker.

### 2. Multi-Tiered Quality Checking
1. **In-Memory Preflight** (`ValidationService.preflight_svg_text`): Rejects illegal tags (`<style>`, `<foreignObject>`), unencoded base64 payloads, and text overflow before saving to disk.
2. **Early Quality Gate** (Post-Slide 5): Validates that design tokens, root fonts, and canvas margins are clean before completing the deck.
3. **Final Quality Gate** (`svg_quality_checker.py --stage final`): Enforces publication-grade criteria (zero blocking issues) prior to compilation.
4. **Package Integrity Check**: `python-pptx` opens and inspects the compiled OpenXML zip package to ensure zero corrupt slides or malformed XML parts.

### 3. State Persistence & Checkpoint Resumption
- Every phase transition writes progress percentages, timestamps, and step outcomes to the SQLite database (`data/jobs.db`).
- If an environment failure occurs, the engine supports **checkpoint resumption** (`app/orchestration/workflow.py:resume_job`), picking up from `PLANNING`, `DESIGN`, or `CONSTRUCTION` without re-running completed work.

---

## 7. Summary

The PPT Master standalone system balances **AI creative synthesis** with **rigid engineering determinism**:
1. **AI Models** generate the narrative outline, extract technical facts, establish color palettes, create contextual photos, and author SVG layouts.
2. **Deterministic Python Services** govern the state machine, sanitize markup, sync vector icons, enforce quality gates, and compile native DrawingML OpenXML files.
3. **PowerPoint Animations** operate automatically through strict `<g id="...">` semantic container authoring coupled with `svg_to_pptx.py -a auto`.

This guarantees that every presentation produced is high-density, visually dynamic, strictly compliant, and natively editable in PowerPoint.
