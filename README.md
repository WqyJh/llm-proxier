# LLM Proxier

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0+-green.svg)](https://fastapi.tiangolo.com/)

A lightweight LLM (Large Language Model) proxy with comprehensive request logging and admin dashboard. This proxy allows you to intercept, log, and monitor all API requests to OpenAI-compatible services while maintaining full compatibility with the original API.

## Features

🚀 **Key Features:**
- **Transparent Proxy**: Seamlessly forwards requests to OpenAI-compatible APIs without modification
- **Comprehensive Logging**: Records all API requests and responses with metadata
- **Admin Dashboard**: Web-based interface for viewing and analyzing request logs
- **Authentication**: Secure API key authentication for both proxy and upstream services
- **Streaming Support**: Full support for streaming responses
- **Database Integration**: Persistent storage using SQLite with async SQLAlchemy

## Architecture

```
┌─────────────────┐    ┌───────────────────┐    ┌───────────────────┐
│   Client App    │───▶│    LLM Proxy      │───▶│   OpenAI API      │
│                 │    │                   │    │                   │
│ - API Requests  │    │ - Authentication  │    │ - GPT Models      │
│ - Streaming     │    │ - Request Logging │    │ - Embeddings      │
│ - Non-Streaming │    │ - Response Relay  │    │ - Other Services  │
└─────────────────┘    │ - Admin Dashboard │    └───────────────────┘
                       └───────────────────┘
                              │
                       ┌──────────────────┐
                       │   SQLite DB      │
                       │                  │
                       │ - Request Logs   │
                       │ - Metadata       │
                       │ - Analytics      │
                       └──────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.12+
- pip or uv package manager
- SQLite (included with Python)

### Installation

1. **Install from PyPI**
```bash
pip install llm-proxier==0.1.4
```

2. **Or install from source**
```bash
# Clone the repository
git clone https://github.com/WqyJh/llm-proxier.git
cd llm-proxier

# Install with pip
pip install -e .
```

3. **Configure environment variables**
```bash
cp .env.example .env
```

Edit `.env` file with your configuration:
```bash
# Proxy Configuration
PROXY_API_KEY=your-proxy-api-key
UPSTREAM_BASE_URL=https://api.openai.com/v1
UPSTREAM_API_KEY=your-upstream-api-key

# Admin Dashboard
ADMIN_USERNAME=admin
ADMIN_PASSWORD=password

# Database
AUTO_MIGRATE_DB=true
```

4. **Run the application**
```bash
# Using the CLI command
llm-proxier

# Or directly
python -m llm_proxier.main

# With custom host and port
llm-proxier --host 0.0.0.0 --port 8000
```

## Usage

### API Requests

All requests are proxied to the upstream OpenAI-compatible API with the same format:

```bash
# Chat completion
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### Admin Dashboard

Access the admin dashboard at `http://localhost:8000/admin`:

- **Login**: Use credentials from `ADMIN_USERNAME` and `ADMIN_PASSWORD`
- **View Logs**: Browse all API requests with filtering and search
- **Real-time Updates**: Live request monitoring

### Request Logging

The proxy automatically logs:
- Request method and path
- Request body (JSON)
- Response body
- HTTP status code
- Timestamp
- Success/failure status

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PROXY_API_KEY` | API key for proxy authentication | Required |
| `UPSTREAM_BASE_URL` | Upstream OpenAI API URL | `https://api.openai.com/v1` |
| `UPSTREAM_API_KEY` | API key for upstream service | Required |
| `ADMIN_USERNAME` | Admin dashboard username | `admin` |
| `ADMIN_PASSWORD` | Admin dashboard password | `password` |
| `AUTO_MIGRATE_DB` | Auto-run database migrations | `true` |

### Database

The application uses SQLite for data persistence. Database files are stored in the application directory. For production use, consider:

- Regular database backups
- Database optimization for large log volumes
- Migration to PostgreSQL/MySQL for scalability

## Development

### Project Structure

```
llm-proxier/
├── src/
│   └── llm_proxier/
│       ├── __init__.py
│       ├── admin.py          # Admin dashboard interface
│       ├── config.py         # Configuration management
│       ├── database.py       # Database models and operations
│       ├── main.py          # Application entry point
│       ├── proxy.py         # Proxy routing and logic
│       └── assets/          # Static assets
│           └── icon.svg
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── uv.lock
```

### Development Setup

1. **Install development dependencies**
```bash
uv sync
```

2. **Run code formatting**
```bash
ruff format
```

3. **Run linting**
```bash
ruff check
```

4. **Pre-commit hooks**
```bash
pre-commit install
pre-commit run --all-files
```

### Testing

```bash
# Run tests (when available)
pytest

# Run with coverage
pytest --cov=src/llm_proxier
```

## API Compatibility

This proxy is compatible with OpenAI API specifications:
- ✅ Chat Completions
- ✅ Streaming responses

## Performance Considerations

- **Database Indexing**: Automatic indexing on request logs for fast queries
- **Async I/O**: Full async/await implementation for high concurrency
- **Streaming Support**: Efficient streaming without buffering entire responses
- **Connection Pooling**: HTTP connection reuse for upstream services

## Security

- **API Key Validation**: All requests require valid proxy API key
- **Authentication Proxying**: Upstream API keys are securely passed through
- **Input Validation**: JSON parsing with error handling
- **Admin Protection**: Separate authentication for admin dashboard

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - High-performance web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - Python SQL toolkit
- [Uvicorn](https://www.uvicorn.org/) - Lightning-fast ASGI server

---

**Star this repository if you find it useful! ⭐**
