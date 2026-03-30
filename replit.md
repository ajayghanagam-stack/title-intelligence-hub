# Title Intelligence Hub — Replit Setup

## Overview
Full-stack AI-powered title document analysis platform with two micro-apps:
- **Title Intelligence** — AI document extraction, risk flags, readiness scores
- **Title Search & Abstracting** — County record searches, chain-of-title, abstract packages

## Architecture
- **Frontend**: Next.js 14 (port 5000)
- **Backend**: FastAPI + SQLAlchemy async (port 8000)
- **Database**: Replit PostgreSQL (via `DATABASE_URL` and `ASYNC_DATABASE_URL` env vars)
- **Pipeline**: FastAPI `background_tasks` (Temporal replaced for Replit compatibility)

## Running the App
The "Start application" workflow runs `bash start.sh`, which:
1. Runs Alembic DB migrations (`alembic upgrade head`)
2. Seeds initial data (admin user, micro apps, demo org)
3. Starts FastAPI backend on `:8000`
4. Starts Next.js frontend on `:5000`

## Default Login Credentials
- **Platform Admin**: `admin@logikality.com` / `admin123`
- **Customer Demo**: `admin@societytitle.com` / `admin123`

## Key Environment Variables
- `DATABASE_URL` — set automatically by Replit (postgresql://)
- `ASYNC_DATABASE_URL` — asyncpg-compatible URL for SQLAlchemy (set as shared env var)
- `PIPELINE_BACKEND` — set to `background_tasks` (no Temporal/Docker required)
- `DEBUG` — set to `true` for dev (allows default JWT secret)
- `GOOGLE_API_KEY` — needed for Gemini AI features
- `ANTHROPIC_API_KEY` — needed if using Claude as AI provider

## API Keys Needed
To use AI features, set these secrets:
- `GOOGLE_API_KEY` (for Gemini, default AI provider)
- `ANTHROPIC_API_KEY` (optional, for Claude)

## Security Notes
- Client/server properly separated: frontend on 5000, API on 8000
- CORS configured to allow Replit domains
- JWT auth with `DEBUG=true` for dev (change `JWT_SECRET` for production)
- Security headers (CSP, HSTS, X-Frame-Options) set in Next.js config

## Project Structure
```
frontend/       Next.js app (port 5000)
backend/        FastAPI app (port 8000)
  app/
    api/        REST API routes
    core/       Auth, middleware, deps
    micro_apps/ Title Intelligence + Title Search plugins
    models/     SQLAlchemy ORM models
    services/   Business logic
  alembic/      DB migrations
  scripts/      seed.py, seed_county_sources.py
start.sh        Replit startup script
```
