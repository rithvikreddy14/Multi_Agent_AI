# Project Structure

```text
nexus-platform/
├── .github/                        # GitHub workflows and repository templates
│   ├── workflows/
│   │   ├── backend-tests.yml       # CI pipeline for backend validation
│   │   └── frontend-tests.yml      # CI pipeline for frontend validation
│   └── PULL_REQUEST_TEMPLATE.md    # Standardized PR template
│
├── frontend/                       # React 18 + Vite + Tailwind Frontend
│   ├── public/
│   │   └── favicon.ico             # Application favicon
│   ├── src/
│   │   ├── api/                    # API communication layer
│   │   │   ├── client.js           # Axios client configuration
│   │   │   ├── claimsApi.js        # Phase 1: Claims & fraud APIs
│   │   │   ├── knowledgeApi.js     # Phase 2: Knowledge base APIs
│   │   │   └── analystApi.js       # Phase 3: Data analyst APIs
│   │   ├── assets/                 # Static assets (logos, icons)
│   │   ├── components/
│   │   │   ├── chat/               # Phase 1: Customer interaction UI
│   │   │   │   ├── MessageBubble.jsx
│   │   │   │   ├── TypingIndicator.jsx
│   │   │   │   └── ClaimFunnel.jsx # Guided fraud complaint workflow
│   │   │   ├── dashboard/          # Phase 4: Monitoring & operations
│   │   │   │   ├── FraudQueue.jsx  # High-risk claim review queue
│   │   │   │   └── Metrics.jsx     # Fraud and system analytics
│   │   │   ├── charts/             # Phase 3: Data visualization
│   │   │   │   └── DynamicChart.jsx
│   │   │   └── shared/             # Reusable UI components
│   │   ├── pages/
│   │   │   ├── CustomerPortal.jsx  # Phase 1: Customer self-service portal
│   │   │   ├── KnowledgeBase.jsx   # Phase 2: RAG-powered document search
│   │   │   ├── DataAnalyst.jsx     # Phase 3: Natural language analytics
│   │   │   └── AdminPanel.jsx      # Phase 4: Operations dashboard
│   │   ├── store/                  # Zustand state management
│   │   │   ├── useChatStore.js
│   │   │   └── useAuthStore.js
│   │   ├── App.jsx                 # Application routes and layout
│   │   └── main.jsx                # Frontend entry point
│   ├── package.json                # Frontend dependencies
│   ├── tailwind.config.js          # Tailwind CSS configuration
│   └── vite.config.js              # Vite build configuration
│
├── backend/                        # FastAPI Multi-Agent Backend
│   ├── app/
│   │   ├── main.py                 # FastAPI startup and app initialization
│   │   ├── api/
│   │   │   ├── routes_orders.py    # Phase 1: Deterministic order tracking
│   │   │   ├── routes_claims.py    # Phase 1: Claims submission endpoints
│   │   │   ├── routes_knowledge.py # Phase 2: RAG upload & retrieval APIs
│   │   │   ├── routes_analyst.py   # Phase 3: Text-to-SQL analytics APIs
│   │   │   └── routes_webhook.py   # Phase 4: WhatsApp/Twilio webhooks
│   │   ├── agents/
│   │   │   ├── orchestrator.py     # Phase 4: LangGraph workflow orchestration
│   │   │   ├── agent_customer.py   # Phase 1: Customer verification agent
│   │   │   ├── agent_rag.py        # Phase 2: Knowledge retrieval agent
│   │   │   └── agent_analyst.py    # Phase 3: Analytics & SQL generation agent
│   │   ├── core/
│   │   │   ├── config.py           # Environment configuration management
│   │   │   ├── fraud_engine.py     # Phase 1: 15-signal fraud detection engine
│   │   │   ├── guardrails.py       # Phase 4: Safety and intent routing
│   │   │   └── security.py         # Authentication, JWT, PII masking
│   │   ├── db/
│   │   │   ├── neon_pg.py          # PostgreSQL connection layer
│   │   │   ├── chroma.py           # Chroma vector database setup
│   │   │   └── redis_session.py    # Shared memory/session storage
│   │   ├── models/
│   │   │   ├── domain.py           # SQLAlchemy database models
│   │   │   └── schemas.py          # Pydantic request/response schemas
│   │   └── services/
│   │       ├── image_checker.py    # Phase 1: Image validation & pHash checks
│   │       ├── document_parser.py  # Phase 2: PDF/DOCX ingestion pipeline
│   │       └── charting.py         # Phase 3: Plotly chart generation
│   └── requirements.txt            # Backend dependencies
│
├── infra/                          # Infrastructure configurations
│   ├── nginx/
│   │   └── default.conf            # Reverse proxy configuration
│   ├── db_migrations/
│   │   └── env.py                  # Alembic migration configuration
│   └── seed_data.sql               # Demo users, orders, and claims data
│
├── data/                           # Local development storage (gitignored)
│   ├── chroma_db/                  # Local vector database persistence
│   └── temp_uploads/               # Temporary file uploads
│
├── .env.example                    # Sample environment variables
├── .gitignore                      # Git ignore rules
└── README.md                       # Project documentation
```

# Development Roadmap

## Phase 1 — Fraud Operations Assistant

**Goal:** Build a customer-facing claims and fraud verification system.

### Features
- Order tracking
- Claims submission workflow
- Image validation and duplicate detection
- Deterministic fraud scoring engine
- Customer support chat interface

### Core Modules
- `routes_orders.py`
- `routes_claims.py`
- `agent_customer.py`
- `fraud_engine.py`
- `image_checker.py`
- `CustomerPortal.jsx`
- `ClaimFunnel.jsx`

---

## Phase 2 — Enterprise Knowledge Assistant

**Goal:** Enable organizations to query internal documents using RAG.

### Features
- PDF/DOCX ingestion
- Document chunking
- Embedding generation
- Vector search with ChromaDB
- Conversational knowledge retrieval

### Core Modules
- `routes_knowledge.py`
- `agent_rag.py`
- `document_parser.py`
- `chroma.py`
- `KnowledgeBase.jsx`

---

## Phase 3 — Natural Language Data Analyst

**Goal:** Allow users to perform analytics using natural language.

### Features
- Text-to-SQL generation
- Database querying
- Automated chart generation
- Interactive analytics dashboard

### Core Modules
- `routes_analyst.py`
- `agent_analyst.py`
- `charting.py`
- `DynamicChart.jsx`
- `DataAnalyst.jsx`

---

## Phase 4 — Multi-Agent AI Operations Platform

**Goal:** Connect all agents into a unified AI operating system.

### Features
- LangGraph orchestration
- Multi-agent routing
- WhatsApp integration
- Shared memory with Redis
- Guardrails and safety checks
- Administrative monitoring dashboard

### Core Modules
- `orchestrator.py`
- `routes_webhook.py`
- `guardrails.py`
- `redis_session.py`
- `FraudQueue.jsx`
- `Metrics.jsx`
- `AdminPanel.jsx`

---

## Final Architecture

The platform evolves from a fraud detection assistant into a complete multi-agent AI operations system:

1. **Customer Agent** → Handles claims and fraud verification.
2. **Knowledge Agent** → Answers questions from enterprise documents.
3. **Analyst Agent** → Performs SQL analytics and visualization.
4. **Orchestrator Agent** → Routes tasks between specialized agents.
5. **Admin Dashboard** → Provides monitoring, review queues, and operational insights.

This phased approach enables incremental delivery while building toward a scalable enterprise-grade multi-agent AI platform.
