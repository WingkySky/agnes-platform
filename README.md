# 🎨 Agnes AI Platform · Image & Video Generation Platform

**Frontend (Vue 3 + Vite)**  | **Backend (FastAPI + Async)**  | **SQLite / PostgreSQL**  | **Agnes AI API Integration**  | **Auto-Polling**

**🌐 Language / 语言**

[**English** ](README.md) | [中文](README_zh.md)

**A full-stack web application for generating images and videos using the Agnes Image 2.1 Flash and Agnes Video V2.0 APIs — with a beautiful Element Plus UI, async backend, and persistent generation history.**

This is not just a demo. It's a production-ready platform featuring a clean separation between a **Vue 3 + Vite frontend** and a **FastAPI backend** (the BFF layer). The backend handles API key security, async task polling, and database persistence — so your API key never touches the browser.

Designed for developers who want a complete, working platform — with zero heavy frontend dependencies and no OpenAI SDK lock-in.

## ✨ Features

### Currently Supported

| Mode | Description | Route |
|---|---|---|
| 🖼️ **Text-to-Image** | Generate images from text prompts (sync or async task mode) | `ImageView.vue` |
| 🖼️ **Image-to-Image** | Modify existing images based on prompts + input image | `ImageView.vue` |
| 🎬 **Text-to-Video** | Generate videos from text prompts (async with auto-polling) | `VideoView.vue` |
| 🎬 **Image-to-Video** | Generate videos from input images — single image, multi-image, and keyframe animation modes | `VideoView.vue` |
| 📜 **Generation History** | Persistent history with type filtering, detail view, batch delete, thumbnail preview | `HistoryView.vue` |

### Architecture Highlights

- **Full-stack separation** — Vue 3 frontend ↔ FastAPI BFF layer ↔ Agnes AI official API

- **API Key security** — Key stored only on the server, never exposed to the browser

- **Async-first backend** — FastAPI + httpx.AsyncClient + SQLAlchemy AsyncSession — images and videos never block each other

- **Independent async task managers** — `image_poller` and `video_poller` run in separate asyncio.Tasks, with their own lifecycle and cleanup

- **Video streaming proxy** — Solves CORS issues for Google Storage-hosted videos, supports Range requests for seek

- **Video thumbnail / GIF preview** — Server-side ffmpeg-based frame extraction for history list visualization

- **Zero heavy frontend framework lock-in** — Vue 3 Composition API, Vite, Element Plus, Pinia, Vue Router, Axios — the standard, proven stack

## 🏗️ Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3 (Composition API) + Vite + Vue Router + Pinia + Axios + Element Plus |
| Backend | Python 3.10+ · FastAPI · SQLAlchemy (sync + async) · httpx (Async HTTP client) |
| Database | SQLite (default) / PostgreSQL (optional, via `DATABASE_URL`) |
| AI Provider | Agnes AI (`https://apihub.agnes-ai.com/v1`) |
| System dependency | `ffmpeg` (for video thumbnails & GIF previews) |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    User Browser (Chrome/Safari...)           │
│  ┌──────────────────────────┐   ┌─────────────────────────┐ │
│  │   Vue 3 SPA (frontend)   │   │  Results / History UI   │ │
│  │  - Image/Video pages     │   │  - Download / Preview   │ │
│  │  - History page          │   └─────────────────────────┘ │
│  │  - Element Plus UI       │                                 │
│  └──────────────────────────┘                                 │
└────────────┬─────────────────────────────────────────────────┘
             │ HTTP / JSON (Vite dev proxy or production static files)
             ▼
┌─────────────────────────────────────────────────────────────┐
│                BFF Layer - FastAPI (backend)                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  Routes: /api/images, /api/videos, /api/history, ...   │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  Services: agnes_client (Agnes AI API encapsulation)    │ │
│  │            video_poller (video async task poller)       │ │
│  │            image_poller (image async task poller)       │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SQLAlchemy → SQLite / PostgreSQL (history persistence) │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────┬─────────────────────────────────────────────────┘
             │ HTTP / JSON (with Bearer Token)
             ▼
┌─────────────────────────────────────────────────────────────┐
│               Agnes AI Official API (apihub.agnes-ai.com)    │
└─────────────────────────────────────────────────────────────┘
```

## 📦 Project Structure

```
agnes-platform/
├── README.md                          # Project documentation (English) — this file
├── README_zh.md                       # Project documentation (Chinese)
├── API.md                             # REST API interface documentation
├── .gitignore
│
├── frontend/                          # Frontend (Vue 3 + Vite)
│   ├── package.json
│   ├── requirements.txt               # NPM dependencies
│   ├── vite.config.js                 # Vite config (proxy /api → backend:8000)
│   ├── index.html
│   ├── .env.example                   # Frontend env var template
│   └── src/
│       ├── main.js                    # Entry — mounts Element Plus / Router / Pinia
│       ├── App.vue                    # Root component
│       ├── router/index.js            # Route configuration
│       ├── stores/                    # Pinia global state
│       │   └── taskQueue.js
│       ├── api/                       # axios wrapper & API requests
│       │   ├── client.js
│       │   ├── images.js
│       │   ├── videos.js
│       │   └── history.js
│       ├── components/                # Reusable components
│       │   ├── ImageUploader.vue
│       │   ├── PromptTemplates.vue
│       │   ├── TaskCard.vue
│       │   └── TaskQueuePanel.vue
│       ├── views/                     # Page-level components
│       │   ├── ImageView.vue
│       │   ├── VideoView.vue
│       │   └── HistoryView.vue
│       └── assets/                    # CSS styles & static resources
│           └── main.css
│
└── backend/                           # Backend (FastAPI)
    ├── requirements.txt               # Python dependencies
    ├── start.sh                       # One-click startup script
    ├── stop.sh                        # Service stop script
    ├── .env.example                   # Backend env var template
    └── app/
        ├── main.py                    # FastAPI entry — route registration, CORS, lifespan
        ├── core/                      # Core configuration
        │   ├── config.py              # pydantic-settings env var loading
        │   └── database.py            # SQLAlchemy engine / session / Base (sync + async)
        ├── models/                    # ORM models
        │   └── generation.py          # Generation model (history records)
        ├── schemas/                   # Pydantic request / response schemas
        │   ├── common.py
        │   ├── images.py
        │   └── videos.py
        ├── services/                  # Business service layer
        │   ├── agnes_client.py        # Agnes AI API client (httpx.AsyncClient pool)
        │   ├── image_poller.py        # Image async task poller
        │   └── video_poller.py        # Video async task poller (independent)
        └── routes/                    # API routes
            ├── images.py              # POST /api/images/tasks, GET /api/images/tasks/{id}
            ├── videos.py              # POST /api/videos, GET /api/videos/{id}, stream proxy
            ├── history.py             # GET/DELETE/batch /api/history, thumbnail + preview
            └── config.py              # Config endpoints
```

## 🚀 Quick Start

Up and running in 3 minutes:

### Step 0: Prerequisites

| Tool | Minimum Version | Why |
|---|---|---|
| **Python** | 3.10+ (recommended 3.11+) | Backend runtime, asyncio features |
| **Node.js** | 18+ (recommended 20+ LTS) | Vite & npm install |
| **ffmpeg** | Any recent version | **Required** — video thumbnail & GIF preview generation |
| **Agnes AI API Key** | — | Get from [platform.agnes-ai.com](https://platform.agnes-ai.com/) |

### Step 1: Install System Dependencies (ffmpeg)

**ffmpeg is required for video thumbnails and GIF previews.** Without it, the history page will still work, but thumbnail extraction will fail gracefully.

```bash
# macOS (via Homebrew)
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg

# CentOS / RHEL
sudo yum install -y ffmpeg

# Windows (via Chocolatey)
choco install ffmpeg

# Verify installation
ffmpeg -version
```

### Step 2: Install Backend Dependencies & Configure

```bash
cd backend

# (Recommended) Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and set your AGNES_API_KEY
```

### Step 3: Start the Backend

```bash
# Inside the backend/ directory

# Option A — use the startup script (recommended, handles port check & venv)
chmod +x start.sh
./start.sh

# Option B — manual start
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify the backend:
- **Health check**: http://localhost:8000/health
- **API docs (Swagger UI)**: http://localhost:8000/docs

### Step 4: Install & Start the Frontend

In a **new terminal window**:

```bash
cd frontend

# Install dependencies
npm install

# (Optional) Configure frontend env vars (usually not needed in development)
cp .env.example .env

# Start the development server (default port 5173, Vite auto-proxies /api → backend:8000)
npm run dev
```

Visit http://localhost:5173 to use the platform.

✨ **That's it!** You now have a working full-stack image & video generation platform.

---

## 📖 Complete Usage Reference

### Image Generation (Text-to-Image / Image-to-Image)

Visit the **Image** page (`/images`) in the web UI.

| Parameter | Description | Default |
|---|---|---|
| **Prompt** | Text description of the desired image | **required** |
| **Mode** | `text2image` or `image2image` | `text2image` |
| **Image** (image2image mode) | Upload a local image (auto-converted to base64) | None |
| **Model** | Agnes AI image model | `agnes-image-2.1-flash` |
| **Size** | Output image size — `1024x1024`, `512x512`, `1024x512`, `512x1024` | `1024x1024` |
| **Response Format** | `url` (download link) or `b64_json` (base64 inline) | `url` |

**Two execution modes are supported on the backend:**
- **Async task mode** (recommended): POST `/api/images/tasks` → returns `task_id` immediately, poll GET `/api/images/tasks/{task_id}` for status. Non-blocking, queue-friendly.
- **Synchronous mode** (backward-compatible): POST `/api/images/generations` → blocks until complete, returns URL directly.

### Video Generation (Text-to-Video / Image-to-Video / Keyframes)

Visit the **Video** page (`/videos`) in the web UI.

| Parameter | Description | Default |
|---|---|---|
| **Prompt** | Text description of the desired video | **required** |
| **Mode** | `text2video`, `image2video`, or `keyframes` | `text2video` |
| **Image(s)** (image2video / keyframes) | Upload local image(s) or provide public URL(s) | None |
| **Model** | Agnes AI video model | `agnes-video-v2.0` |
| **num_frames** | Total frames — must satisfy `8n+1` (e.g. 33, 49, 81, 121, 241, 441) | `121` |
| **frame_rate** | Frame rate (1–60) | `24` |
| **width / height** | Video resolution in pixels | `1152 / 768` |
| **negative_prompt** | Description of what to avoid | None |
| **seed** | Random seed for reproducibility | Random |

**Approximate duration by frame count** (at 24 fps):

| num_frames | Duration |
|---|---|
| 33 | ~1.4s |
| 81 | ~3.4s |
| 121 | ~5.0s |
| 241 | ~10.0s |
| 441 | ~18.4s |

⚠️ **Note:** Agnes Video API requires publicly accessible image URLs for image-to-video and keyframe modes.

### Generation History

Visit the **History** page (`/history`) in the web UI.

- Filter by type: **All / Image / Video**
- View details: click any record to see prompt, parameters, result URL
- Delete single records or batch-delete via checkbox selection
- Video records show auto-extracted **thumbnails** and hover **GIF previews**

## 📋 API Details

### Image API (Backend → Agnes AI)

- **Base URL**: `https://apihub.agnes-ai.com/v1`
- **Endpoint**: `POST /images/generations`
- **Model**: `agnes-image-2.1-flash`
- **Auth**: Bearer token via `Authorization: Bearer $AGNES_API_KEY`
- **Format**: OpenAI-compatible API

### Video API (Backend → Agnes AI)

- **Base URL**: `https://apihub.agnes-ai.com/v1`
- **Poll URL**: `https://apihub.agnes-ai.com/agnesapi`
- **Model**: `agnes-video-v2.0`
- **Flow**:
    1. `POST /videos` → creates async task, returns `task_id` / `video_id`
    2. `GET /agnesapi?video_id=...` (or `GET /videos/{task_id}`) → polls for completion
    3. Status progresses: `in_progress` → `completed`
    4. Download video from the returned URL
- **Auth**: Bearer token via `Authorization: Bearer $AGNES_API_KEY`

### Frontend ↔ Backend API

Full endpoint documentation is available in [API.md](API.md). Quick summary:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/images/tasks` | Create image async task |
| `GET` | `/api/images/tasks/{task_id}` | Poll image task status |
| `POST` | `/api/videos` | Create video async task |
| `GET` | `/api/videos/{task_id}` | Poll video task status |
| `GET` | `/api/videos/{task_id}/stream` | Proxy-play video stream (CORS + Range support) |
| `GET` | `/api/history` | Paginated generation history list |
| `DELETE` | `/api/history/{id}` | Delete single history record |
| `POST` | `/api/history/batch-delete` | Batch delete records |
| `GET` | `/api/history/video/{id}/thumbnail` | Video first-frame thumbnail (JPEG) |
| `GET` | `/api/history/video/{id}/preview` | Video preview GIF |

## 🛠️ Architecture Overview

```
frontend/src/views/ImageView.vue
frontend/src/views/VideoView.vue   }  Vue 3 SPA (UI layer)
frontend/src/views/HistoryView.vue

         │ HTTP / JSON (axios)
         ▼

backend/app/routes/images.py
backend/app/routes/videos.py        }  FastAPI route layer
backend/app/routes/history.py

         │ async/await
         ▼

backend/app/services/agnes_client.py       }  Business service layer
backend/app/services/image_poller.py       }  (httpx.AsyncClient pool,
backend/app/services/video_poller.py       }   independent asyncio.Tasks)

         │ async/await
         ▼

backend/app/core/database.py        }  SQLAlchemy 2.0 — AsyncSession + sync fallback
backend/app/models/generation.py    }  ORM model — history persistence

         │ async/await
         ▼

SQLite (default, zero-config)       }  Persistence layer
PostgreSQL (optional, DATABASE_URL)
```

- **UI layer (`frontend/src/views/*.vue`)** — Vue 3 components with Element Plus. User interactions trigger axios API calls to the BFF.
- **Route layer (`backend/app/routes/*.py`)** — FastAPI async endpoints. Validates input, calls services, returns structured JSON responses.
- **Service layer (`backend/app/services/*.py`)** — `agnes_client` is a shared httpx.AsyncClient pool. `image_poller` and `video_poller` are *independent* managers, each with its own asyncio.Task lifecycle, polling logic, and cleanup — they never block each other.
- **Persistence layer (`backend/app/core/database.py` + `models/generation.py`)** — SQLAlchemy 2.0 with both sync and async sessions. Default: SQLite (zero config). Switch to PostgreSQL by changing `DATABASE_URL`.

## 💡 Switching to PostgreSQL (Optional)

The platform defaults to SQLite — zero configuration, works out of the box. To switch to PostgreSQL:

1. Install the driver: `pip install psycopg2-binary`
2. In `backend/.env`, set:
   ```
   DATABASE_URL=postgresql://username:password@localhost:5432/agnes_platform
   ```
3. Restart the backend — SQLAlchemy handles the rest automatically

## 📦 Dependencies Reference

### Frontend (NPM)

| Package | Purpose |
|---|---|
| `vue` | Core framework (Composition API) |
| `vue-router` | SPA routing |
| `pinia` | Global state management |
| `axios` | HTTP client for API calls |
| `element-plus` | UI component library (dark theme) |
| `@element-plus/icons-vue` | Icon set |
| `vite` (dev) | Build tool & dev server |
| `@vitejs/plugin-vue` (dev) | Vue 3 support for Vite |

### Backend (Python)

| Package | Purpose |
|---|---|
| `fastapi` | Async-first web framework |
| `uvicorn[standard]` | ASGI server |
| `pydantic-settings` | `.env` + environment variable loading |
| `python-dotenv` | `.env` file parsing (used by pydantic-settings) |
| `SQLAlchemy` | ORM + async database sessions |
| `httpx` | Async HTTP client (connection-pooled calls to Agnes AI) |
| `aiosqlite` | Async SQLite driver (required for AsyncSession with SQLite) |
| `greenlet` | Required for SQLAlchemy async internals |
| `aiofiles` | Reserved for future async file operations |

### System

| Tool | Purpose |
|---|---|
| `ffmpeg` | **Required for video thumbnails & GIF previews** — extracts the first frame and generates a ~3-second preview GIF. Without it, the history page gracefully degrades. |

## ❓ FAQ

**Q: Why the BFF layer? Why not just call Agnes AI directly from the browser?**

A: A pure-frontend architecture has two critical problems: (1) API key exposed in browser JavaScript, easily stolen. (2) No way to persist history or manage server-side tasks. With the BFF layer, your API key stays on the server — significantly more secure.

**Q: How long does video generation take?**

A: Usually 2–6 minutes. The platform auto-polls in the background, and the frontend shows real-time progress. You can navigate away and check the History page later.

**Q: Where are my generated images/videos stored?**

A: Media files are hosted by Agnes AI and returned as public URLs. Your local SQLite database stores prompt, parameters, and result URLs for history.

**Q: Can I deploy this to production?**

A: Yes. Build the frontend (`npm run build` → `frontend/dist/`) and serve it statically (Nginx / Caddy). Deploy the backend with any ASGI-compatible host (Uvicorn behind Nginx, Fly.io, Railway, etc.). Set `FRONTEND_ORIGINS` to your production domain and `DATABASE_URL` to your production database.

## 📜 License

MIT © Agnes AI Platform

[image-generation](https://github.com/topics/image-generation) [video-generation](https://github.com/topics/video-generation) [agnes-ai](https://github.com/topics/agnes-ai)
