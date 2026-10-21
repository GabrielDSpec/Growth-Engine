# Corporate Specification
## Growth Engine

**Version:** 1.0  
**Date:** October 21, 2026  
**Classification:** Executive and technical presentation document

## 1. Executive summary

Growth Engine is an editorial intelligence and content production platform for YouTube channels. It transforms historical data, transcripts, performance signals, and external context into traceable editorial decisions: which topics deserve attention, which moments can become Shorts, how metadata should be prepared, and how the result can be distributed.

The platform combines first-party channel analysis, local artificial intelligence, media automation, and persistent job management. It is designed to reduce the manual work between discovering an opportunity and publishing short-form content while preserving evidence and enabling human review before irreversible actions.

The functional core already exists. The next step toward a corporate offering is to consolidate structural tenant isolation, access governance, observability, publication idempotency, and controlled operational validation.

## 2. Business problem

Recurring Shorts production usually requires a fragmented sequence of activities:

- interpret the channel history;
- identify topics and formats that perform well;
- transcribe long-form videos;
- locate relevant moments;
- edit and frame the video;
- write the title and description;
- relate the Short to its source video;
- publish or schedule it;
- maintain traceability over content that has already been used.

Without an intelligence and control layer, the process tends to create rework, repeated cuts, decisions based on incorrect context, loss of evidence, and duplicate-publication risk.

## 3. Value proposition

Growth Engine delivers an evidence-oriented editorial pipeline:

1. **Understand the library:** synchronize videos, metrics, and classifications.
2. **Understand the channel:** produce content autopsies, semantic profiles, and editorial history.
3. **Find opportunities:** combine first-party evidence with external Radar discovery without mixing the sources.
4. **Select moments:** use transcripts, multimodal context, temporal rules, and cross-cycle diversity.
5. **Produce Shorts:** render, validate, and review vertical cuts.
6. **Distribute with control:** edit metadata, publish, or schedule while preserving persistent state.
7. **Learn from the process:** preserve origin, evidence, status, failures, and decisions.

## 4. Functional scope

### 4.1 Channel intelligence

- Synchronization of YouTube videos and metrics.
- Classification of long-form videos and Shorts.
- Individual and batch content autopsies with observations, literal excerpts, hypotheses, and missing data.
- Semantic channel profiles with topics, pillars, and formats.
- Historical editorial analysis and prioritization of relevant videos.

### 4.2 Discovery and planning

- Radar for news, trends, and local or niche context through RSS.
- Opportunities based on the channel's own Content Autopsy.
- Evolving opportunity scores and production briefs.
- Versioned editorial dossier with chapters, summary, heat map, and moments.
- Fingerprints to validate cache and transcript freshness.

**Editorial governance rule:** the Radar is an external discovery source. It does not replace or contaminate the evidence used to generate channel opportunities.

### 4.3 Transcription and evidence

- DirectCompute transcription for AMD or `faster-whisper`.
- SRT, JSON, and processing-sidecar caches.
- Adaptive reprocessing when temporal coverage is insufficient or dominated by acoustic markers.
- Window-level resume support in `faster-whisper`.
- UTF-8 SRT transcript export.

### 4.4 Cut curation and production

- Editorial analysis across time windows.
- Preservation of absolute and relative timestamps.
- Deduplication by temporal overlap and similarity.
- Cross-cycle diversity to avoid reusing the same intervals.
- Prioritization of interviews and substantive speech.
- Validation of titles and descriptions against the actual interval text.
- Individual title or description regeneration.
- 9:16 rendering with FFmpeg.
- AMD AMF encoder when available, with `libx264` fallback.
- Human review before publication.

### 4.5 Publishing and distribution

- Individual, cycle-level, and batch selection.
- Immediate publishing and scheduling.
- Editable metadata per cut.
- Association between a Short and its related long-form video.
- Completion and failure notifications.
- Physical MP4 existence and integrity checks before publishing.

### 4.6 Operations and administration

- Operations Center with job, progress, and ETA views.
- Active-profile switching.
- Local upload by physical path.
- Controlled cache and artifact cleanup.
- Administrative panel for maintenance and service control.
- Backlog and documentation accessible from the Central interface.

## 5. End-to-end flow

```mermaid
flowchart LR
    A[YouTube channel] --> B[Synchronization]
    B --> C[SQLite and cache]
    C --> D[Transcription]
    D --> E[Content Autopsy and semantic profile]
    E --> F[Editorial dossier]
    F --> G[Cut curation]
    G --> H[Human review]
    H --> I[FFmpeg rendering]
    I --> J[Metadata]
    J --> K[Publishing or scheduling]
    K --> L[History and notifications]
    R[RSS Radar] --> P[External discovery]
    P -. separate context .-> E
```

Long-running stages are asynchronous. Each execution is expected to preserve `job_id`, profile, video, stage, attempt, progress, checkpoint, duration, and error information.

## 6. Solution architecture

### 6.1 Current layers

- **Interface:** static SPA in `frontend/index.html`, `frontend/app.js`, and custom CSS.
- **HTTP API and orchestration:** web server in `core/web_server.py`.
- **Domain:** modules for Autopsy, intelligence, profiles, opportunities, dossiers, cuts, and publishing.
- **Persistence:** SQLite with specialized repositories and operational tables.
- **Execution:** `TaskRunner`, persistent jobs, checkpoints, notifications, and restart recovery.
- **Providers:** YouTube, Ollama/Qwen, Whisper, FFmpeg/FFprobe, RSS, and Playwright.
- **Artifacts:** media, transcripts, dossiers, Shorts, and caches organized by profile.

### 6.2 Relevant technical decisions

- Local AI reduces the need to send transcripts to external services.
- Caches and fingerprints prevent expensive processing when the evidence has not changed.
- JSON contracts, retries, and placeholder rejection protect AI output quality.
- CPU rendering provides a fallback when the AMD encoder is unavailable.
- An MP4 is physically validated before it is considered ready.
- Operational state belongs in the database rather than only in the read-only editorial dossier.

### 6.3 Main components

| Component | Responsibility |
|---|---|
| `core/web_server.py` | HTTP API, profile authorization, routes, and current orchestration |
| `core/database.py` | SQLite schema, connections, and migrations |
| `core/job_repository.py` | Jobs, states, checkpoints, duration, and resume |
| `core/task_runner.py` | Asynchronous execution and worker limits |
| `core/transcriber.py` | Whisper, DirectCompute, SRT, JSON, and caching |
| `core/cutter.py` | Curation, editorial validation, and cut preparation |
| `core/media_tools.py` | FFmpeg, crop, blur, encoders, and output validation |
| `core/publisher.py` | Metadata, publishing, and scheduling |
| `core/related_video_studio.py` | YouTube Studio related-video automation |
| `core/radar_sources.py` | RSS providers and normalization |
| `frontend/app.js` | SPA state, workflows, polling, and safe rendering |

### 6.4 Technologies used

| Layer | Technology | Use in Growth Engine |
|---|---|---|
| Main language | Python | Backend, domain rules, workers, provider integrations, and automation |
| HTTP backend | `http.server.ThreadingHTTPServer` | Local web server and concurrent Central routes |
| Frontend | HTML5, CSS3, and JavaScript | Operations SPA, navigation, cards, dialogs, polling, and content review |
| Persistence | SQLite | Profiles, videos, analyses, cuts, jobs, notifications, and encrypted tokens |
| SQLite concurrency | WAL and foreign keys | Durability, concurrent reads, and referential integrity |
| HTTP client | `requests` | YouTube, Ollama, internal endpoints, and HTTP providers |
| Cryptography | `cryptography` / Fernet | OAuth token and secret protection |
| Media download | `yt-dlp` | YouTube video and audio download with retries and cookie support |
| Auxiliary runtime | Node.js | JavaScript challenge support used by some `yt-dlp` flows |
| Local generative AI | Ollama | Serving local models without sending transcripts to an external provider |
| Editorial model | Qwen `qwen2.5:14b` | Autopsy, semantic profile, opportunities, dossier, titles, descriptions, and cuts |
| CPU/CUDA transcription | `faster-whisper` / CTranslate2 | Segmented transcription, caching, and window resume |
| AMD transcription | DirectCompute, `constme.exe`, and Whisper | Local transcription acceleration on AMD GPU |
| Computer vision | `opencv-python` | Face detection and auxiliary visual cut analysis |
| Audiovisual processing | FFmpeg and FFprobe | Duration, scenes, audio, crop, blur, composition, codecs, and MP4 validation |
| Hardware encoder | AMD AMF `h264_amf` | Hardware H.264 rendering when available |
| CPU fallback encoder | `libx264` | CPU rendering when AMF or the AMD device fails |
| Web automation | Playwright | YouTube Studio workflows and related-video association |
| External feeds | RSS and HTTP providers | Local, news, trend, and niche Radar sources |
| Native interface | CustomTkinter | Resident Control Panel for services, jobs, and maintenance |
| Panel utilities | psutil, pystray, and Pillow | Process monitoring, Windows tray integration, and visual resources |
| Packaging | PyInstaller | Windows executable distribution for the Control Panel |
| Testing | `unittest`, mocks, and frontend contracts | Domain, AI, media, persistence, OAuth, and XSS verification |

### 6.5 Runtime environment

- **Primary operating system:** Windows.
- **Backend:** Python interpreter from the project's `.venv` environment.
- **AI acceleration:** AMD Radeon GPU compatible with the configured DirectCompute path; `faster-whisper` remains available as a CPU/CUDA alternative according to the hardware.
- **Media:** FFmpeg and FFprobe installed and accessible to the Growth Engine process.
- **Local AI:** Ollama server at `127.0.0.1:11434` with the configured Qwen model.
- **Automated browser:** persistent Chrome profile outside the workspace for Playwright workflows.
- **Storage:** SQLite, model caches, transcripts, and media artifacts in profile-configured directories.

Python, Node.js, FFmpeg, model, AMD driver, and Python dependency versions should be pinned in a deployment manifest before corporate distribution. The current code detects dependencies through configuration and local availability but does not yet provide a formal versioned compatibility matrix.

## 7. Data model and isolation

The system persists, among other domains:

- profiles and channels;
- historical videos;
- transcripts and analyses;
- semantic classifications;
- opportunities;
- editorial dossiers;
- cuts and artifacts;
- jobs and checkpoints;
- notifications;
- OAuth tokens and preferences.

Current isolation is applied through `perfil_id`, the `X-Profile-Id` header, profile-associated OAuth, and profile-specific media directories.

### Current corporate limitation

Isolation is still predominantly logical. Some historical constraints use global `video_id` values, singleton tables remain, and legacy global directories coexist with profile directories. Full multi-tenant operation requires:

- adopting a composite tenant/profile and video identity;
- reviewing `PRIMARY KEY`, `UNIQUE`, and `ON CONFLICT` clauses;
- migrating singleton tables to tenant scope;
- validating every query against cross-tenant access;
- testing concurrency across profiles;
- standardizing artifact directories.

## 8. Integrations and dependencies

| Integration | Use | Operational dependency |
|---|---|---|
| YouTube Data API | videos, metrics, channels, and publishing | OAuth, quotas, and valid credentials |
| YouTube Analytics | analytics data | authorization and API availability |
| YouTube Studio/Playwright | related-video and API-gap workflows | Chrome session and selectors subject to change |
| yt-dlp | YouTube media/audio download | cookies, network, and YouTube changes |
| Ollama/Qwen | analysis, editorial, titles, and descriptions | local model, VRAM/RAM, and inference time |
| DirectCompute/faster-whisper | transcription | GPU/CPU, models, and runtime |
| FFmpeg/FFprobe | media analysis and rendering | installation, codecs, and encoders |
| RSS/providers | external Radar | source availability and feed formats |
| SQLite | local persistence | backup, migrations, and concurrency policy |

## 9. Security and governance

### Existing controls

- OAuth tokens encrypted with Fernet.
- Refresh-token preservation when the provider does not return a new value.
- CSP and Origin allowlist.
- URL validation and insecure-protocol blocking.
- Profile scope on private routes.
- Administrative checks for maintenance operations.
- DOM-safe rendering and XSS-specific tests.
- Partial physical separation of artifacts by profile.

### Requirements for a corporate product

- RBAC with roles, permissions, and organization/tenant scope.
- Audit trail for login, changes, deletion, publishing, and maintenance.
- Formal secret management and credential rotation.
- Data retention, export, and deletion policy.
- Structured logs without tokens, cookies, or inappropriate personal data.
- Backup, restore, and periodic SQLite recovery tests.
- Strong authentication if the server is exposed beyond the local machine.

## 10. Operations, reliability, and observability

### Available capabilities

- Persistent jobs and terminal states.
- Incremental checkpoints.
- Cooperative cancellation.
- Recovery of interrupted tasks.
- Limited retries for recoverable failures.
- Persistent notifications.
- Job duration measurement.
- Encoder fallback and file validation.

### Priority gaps

- Consolidated queue, latency, throughput, and provider-success metrics.
- Health checks for Ollama, Whisper, FFmpeg, and YouTube.
- Distributed or transactional locks across processes.
- Formal CPU, GPU, memory, and storage limits.
- Complete publishing and scheduling idempotency.
- Configurable timezone per profile.
- Reduced dependence on fixed sleeps and interactive input in the legacy scheduler.

## 11. Current maturity

### Core available

The platform supports the core cycle of analysis, transcription, editorial intelligence, cut selection, rendering, review, and publishing preparation. It has a meaningful base of tests covering contracts, security, persistence, AI, media, and frontend behavior.

### Being consolidated

- Complete DirectCompute transcription resume.
- Backend and frontend modularization.
- Real operational validation of cache miss/hit.
- Real publishing after reauthorization and controlled testing.
- Concurrency, observability, and FFmpeg validation hardening.
- Reliable face framing and styled captions per cut.

### Planned

- Structural multi-tenancy.
- Corporate RBAC and auditing.
- Scale through independent workers and a server-side database.
- Executive reporting and continuous editorial learning.
- Omnichannel distribution.
- Cost, retention, and cloud-operation governance.

## 12. Risks and mitigation

| Risk | Impact | Recommended mitigation |
|---|---|---|
| Cross-tenant collision | data exposure or overwrite | composite keys and cross-tenant tests |
| Local AI failure or latency | stalled queue and inconsistent output | watchdog, timeout, limited retries, health checks, and explicit fallback |
| YouTube Studio changes | related-video automation failure | selector contracts, periodic tests, and assisted manual path |
| Duplicate publishing | operational and reputational impact | idempotency by cut, destination, and confirmed state |
| GPU/codec failure | incomplete rendering | CPU fallback, MP4 validation, and diagnostic artifacts |
| Media/cache growth | storage exhaustion | quotas, retention, audited cleanup, and storage metrics |
| SQLite concurrency | contention and operational risk | transactional locks, backup, and PostgreSQL evaluation |
| Variable editorial quality | poor decisions | textual evidence, human review, evaluation sets, and feedback |

## 13. Recommended roadmap

### Phase 1: Control and integrity

Structural multi-tenancy, migrations, RBAC, auditing, backup, and isolation tests.

### Phase 2: Reliable publishing

Reauthorization, controlled publishing tests, idempotency, profile timezones, and publishing resume.

### Phase 3: Observable operations

Health checks, metrics, structured logs, resource limits, alerts, and operations dashboards.

### Phase 4: Advanced audiovisual production

Temporal face-confidence framing, styled ASS captions, preview, and per-cut retry.

### Phase 5: Platform scale

Handler modularization, independent workers, server-side database, organizations, permissions, and optional cloud execution.

### Phase 6: Continuous intelligence

Editorial DNA, title/format/time experiments, retention, conversion, reporting, and omnichannel distribution.

## 14. Corporate acceptance criteria

The product will be ready for corporate deployment when:

- no tenant can query or overwrite another tenant's data;
- sensitive actions require authorization and produce an audit trail;
- publishing and scheduling are idempotent and resumable;
- critical providers have health checks, timeouts, and metrics;
- backup and restore have been tested;
- transcription, rendering, and publishing have been validated with real media;
- editorial quality has an evaluation set and sample review process;
- AI, storage, and processing costs are measurable;
- captions and framing have been visually validated;
- operational documentation allows recovery without undocumented developer knowledge.

## 15. Executive presentation message

> Growth Engine transforms a channel's library into traceable editorial decisions and distribution-ready content. Its differentiator is the combination of first-party evidence, local artificial intelligence, audiovisual automation, and operational control in one pipeline. The core already works; the corporate agenda is to raise isolation, governance, observability, and scale to the same level as its editorial intelligence.

## Internal references

- [Corporate specification in Portuguese](especificacao_corporativa_growth_engine.md)
- [Project README](../README.md)
- [Modular architecture](arquitetura_modular.md)
- [AI documentation](../documentacao_ia.md)
- [Project backlog](../BACKLOG.md)
- [Implementation history](../historico_implementacoes.md)
- [F4 - Editorial dossier](backlog/features/F4-dossie-editorial.md)
