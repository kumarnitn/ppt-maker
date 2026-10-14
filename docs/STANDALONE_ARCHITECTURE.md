# Standalone PPT Maker — Architecture Specification

## 1. Architectural Mission

The Standalone PPT Maker is an autonomous, API-powered document-to-presentation generation application. It transforms diverse source documents into natively editable, professionally designed PowerPoint presentations using a deterministic internal workflow engine, direct model API integrations, and the battle-tested script engine of PPT Master.

**Core Invariant**: The application executes 100% via standard application code without requiring Antigravity, Cursor, Claude Code, or any runtime AI agent to orchestrate the pipeline. AI models are accessed purely as stateless remote services through structured API requests.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Web UI / CLI Entrypoint                         │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Flask REST API & Job Controller                      │
│       (app/api/routes.py, app/api/jobs.py, app/api/downloads.py)       │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│              Deterministic Workflow Orchestration Engine               │
│                  (app/orchestration/workflow.py)                       │
│    QUEUED ➔ INGESTING ➔ PLANNING ➔ DESIGN ➔ CONSTRUCTION ➔ NOTES ➔     │
│                 FINALIZATION ➔ COMPILATION ➔ COMPLETE                  │
└──────┬───────────────┬───────────────┬────────────────┬──────────┬─────┘
       │               │               │                │          │
       ▼               ▼               ▼                ▼          ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  Document   │ │ Presentation│ │    Asset    │ │ Slide & SVG │ │  Export &   │
│   Service   │ │  Planning   │ │   Service   │ │   Service   │ │ Quality QA  │
│(Doc to MD)  │ │ (LLM Plan & │ │(Flux / Icons│ │(AI Authoring│ │(Validator & │
│             │ │ Design Spec)│ │ & Manifest) │ │  & Repair)  │ │ svg_to_pptx)│
└──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
       │               │               │                │          │
       └───────────────┼───────────────┴────────────────┼──────────┘
                       ▼                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       External Services & Storage                      │
│  • AI Provider Adapters: Azure OpenAI / OpenAI / Azure MaaS Flux 2 Pro │
│  • SQLite Job & State Store (app_data/jobs.db)                         │
│  • File Workspace: projects/<project_slug>_<timestamp>/                │
│  • PPT Master Script Suite: skills/ppt-master/scripts/                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Design & Logical Modules

### 2.1 `document_ingestion` (`app/services/document_service.py`)
* **Role**: Accepts PDF, DOCX, TXT, MD, HTML inputs and normalizes them into Markdown.
* **Mechanism**: Invokes `skills/ppt-master/scripts/source_to_md.py` via safe subprocess execution.
* **Output**: Clean Markdown files stored in `projects/<project>/sources/`.

### 2.2 `document_understanding` & `presentation_planner` (`app/services/planning_service.py`)
* **Role**: Performs semantic analysis, content prioritization, narrative budgeting, and storyboard generation.
* **Mechanism**: Submits source text to configured LLM (Azure OpenAI / OpenAI) using `PLANNING_SYSTEM_PROMPT`.
* **Output**: Strongly-typed `PresentationPlan` validated by Pydantic V2 and saved to `presentation_plan.json`.

### 2.3 `design_system` & `layout_engine` (`app/schemas/spec.py`, `app/ai/prompts.py`)
* **Role**: Establishes typography scale, color palette tokens, margin contracts, and layout templates.
* **Presets**: Default Executive Consulting Light theme (`#FFFFFF` background, `#2B6CB0` corporate blue, `#E86C38` highlight banners).
* **Output**: `design_spec.md` (human-readable) and `spec_lock.md` (machine-enforced immutable constraints).

### 2.4 `asset_manager` (`app/services/asset_service.py`, `app/ai/image_provider.py`)
* **Role**: Coordinates vector icons and contextual photographic imagery.
* **Vector Icons**: Synchronizes requested Tabler icons from `templates/icons/` via `icon_sync.py`.
* **AI Image Generation**: Connects to Flux 2 Pro (Azure AI Studio MaaS or BFL) and Nano Banana (Gemini) to generate high-resolution PNG visuals for key thematic slides.
* **Manifest**: Maintains `images/image_prompts.json` and runs `analyze_images.py`.

### 2.5 `slide_authoring` & `repair_engine` (`app/services/slide_service.py`)
* **Role**: Sequential slide SVG generation and targeted, bounded error repair.
* **Authoring Contract**: 1280x720 canvas, unitless px coordinates, semantic group IDs (`<g id="header">`, `<g id="card-1">`), strict XML well-formedness, no CSS classes.
* **Targeted Repair**: If a slide fails preflight or quality checker bounds, only the failing slide SVG is sent to `repair_slide_svg` with exact line errors (up to `max_retries_per_slide = 3`).

### 2.6 `speaker_notes` (`app/services/notes_service.py`)
* **Role**: Generates concise, professional presenter talking points and transitions.
* **Synchronization**: Writes `notes/total.md` and uses `total_md_split.py` to create 1:1 matching `notes/slide_NN.md` files.

### 2.7 `quality_assurance` (`app/services/validation_service.py`)
* **Multi-Layer QA**:
  * *Layer 1*: Early text overflow, canvas boundary (`x: 60-1220`, `y: 40-660`), and `<tspan>` line-wrapping preflight.
  * *Layer 2*: Final gate via `svg_quality_checker.py --stage final --json --canonical-authoring`.
  * *Layer 3*: OpenXML package and file-integrity validation (`pptx_opc_validation.py`, python-pptx).
  * *Layer 4*: Rendered preview inspection and base64 data URI browser streaming.

### 2.8 `pptx_compiler` (`app/services/export_service.py`)
* **Role**: Compiles SVG assets and notes into native DrawingML `.pptx` presentations.
* **Mechanism**: Invokes `skills/ppt-master/scripts/finalize_svg.py` followed by `svg_to_pptx.py --quick-generate --with-notes`.
* **Dynamic Motion**: Passes `-a auto --animation-trigger after-previous` and `-t push` (or user-selected transition) to inject native PowerPoint animation and transition tags.

### 2.9 `workflow_engine` & `state_store` (`app/orchestration/`)
* **Role**: Manages job lifecycle, state transitions, async execution, logs, and checkpoints.
* **Storage**: SQLite database (`data/jobs.db`) with tables `jobs` and `job_logs`.
* **Resumability**: Jobs can be resumed from intermediate checkpoints (`PLANNING`, `DESIGN`, `CONSTRUCTION`, `EXPORT`).

---

## 3. Security, Configuration & Runtime Isolation

1. **Zero Secret Leakage**:
   * API credentials reside strictly in `.env`.
   * `.env` is listed in `.gitignore` and never committed.
   * `config.redacted_dict()` masks all keys before saving job snapshots or returning API responses.
2. **Subprocess Sanitization**:
   * All script invocations use validated argument lists (no shell string interpolation).
   * Strict timeout enforcement (`subprocess_timeout = 180s`) prevents hanging processes.
3. **Browser Sandbox Isolation**:
   * SVGs served to the web frontend dynamically inline local images as Base64 data URIs to bypass browser `<img>` tag security sandboxing while keeping the on-disk SVGs clean for PPTX compilation.
