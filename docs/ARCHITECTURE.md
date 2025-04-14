# CacheWarp Architecture

## Overview
CacheWarp is a high-performance caching reverse proxy built with **FastAPI** and **Redis**. It is designed to achieve **90ms P99 latency** and handle **8,000+ RPS**, tailored for fintech applications. The Week 1 MVP focuses on:
- Basic caching for `GET` requests.
- A `/health` endpoint.

This sets the foundation for a scalable and reliable proxy.

---

## Achievements (Week 1 MVP - Day 3)
- Successfully implemented caching for `GET` requests.
- `/health` endpoint operational, providing Redis status.

---

## Components

### **1. FastAPI Application (`src/main.py`)**
- **Functionality**: 
  - Hosts the `/health` endpoint that returns:
    ```json
    {"status": "ok", "redis": "<status>"}
    ```
  - Applies caching middleware for all `GET` requests.
- **Lifecycle**:
  - Manages Redis connections using `@asynccontextmanager` via FastAPI’s `lifespan` parameter:
    - **Connect on startup**.
    - **Close on shutdown**.
- **Middleware**:
  - Integrates `caching_middleware` to cache responses with a fallback mechanism for errors.

---

### **2. Configuration (`src/config.py`)**
- **Purpose**:
  - Centralized configuration using **Pydantic** (`pydantic-settings`).
- **Fields**:
  - `redis_url`: Redis connection (`RedisDsn`) - Default: `redis://localhost:6379`.
  - `origin_url`: Upstream API (`HttpUrl`) - Default: `http://localhost:8080`.
  - `cache_default_ttl`: Cache Time-to-Live (TTL) - Default: `30 seconds`.
- **Features**:
  - Support for `.env` files.
  - Case-sensitive environment variables with UTF-8 encoding.

---

### **3. Cache Layer (`src/proxy/cache.py`)**
- **Implementation**:
  - Uses an **asynchronous Redis client** (`redis-py`) with JSON serialization.
- **Methods**:
  - `connect`: Initializes Redis with:
    - **20 max connections**.
    - `decode_responses=True`.
  - `close`: Cleanly closes Redis connections using `aclose()`.
  - `get`: Retrieves and deserializes JSON data from Redis.
  - `set`: Stores JSON data in Redis with a TTL of `30 seconds`.
- **Features**:
  - Handles connection errors gracefully.
  - Ensures binary safety during data storage.

---

### **4. Caching Middleware (`src/proxy/middleware.py`)**
- **Logic**:
  - Caches `GET` responses with:
    - **Status code**: `200`.
    - **Content type**: `application/json`.
- **Flow**:
  1. Checks the cache using `cache.get()`.
  2. If a hit, returns `JSONResponse`.
  3. On a miss:
     - Processes the request.
     - Collects `body_iterator`.
     - Caches JSON responses if valid.
  4. Non-JSON responses (e.g., `/docs` HTML) are passed through unchanged.
- **Robustness**:
  - Validates `content-type`.
  - Handles JSON parsing errors gracefully.

---

### **5. Testing (`tests/test_proxy.py`)**
- **Framework**:
  - Uses `pytest` with `pytest-asyncio` for async test support.
- **Fixtures**:
  - `cache`: Module-scoped fixture to manage Redis connections.
  - `client`: Provides a `TestClient` for interacting with the FastAPI application.
- **Test Case**:
  - `test_caching_flow` verifies:
    1. Cache **miss** for the first `/health` request.
    2. Cache **store** for the response.
    3. Cache **hit** for subsequent requests.
- **Configuration**:
  - `asyncio_mode=auto` ensures stable async event loops for tests.

---

### **6. Infrastructure (`docker/docker-compose.yml`)**
- **Redis**:
  - Image: `redis:7-alpine`.
  - Exposes port `6379`.
  - Includes a healthcheck (`redis-cli ping`) for monitoring.
- **Setup**:
  - Persistent volume: `redis_data`.
  - Lightweight image for efficient deployment.

---

## Conclusion
CacheWarp's architecture leverages **FastAPI** and **Redis** to deliver a robust caching solution for fintech applications. With its modular components and scalable design, it’s set up for rapid iteration and future enhancements.
