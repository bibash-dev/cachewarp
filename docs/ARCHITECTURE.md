# CacheWarp Architecture

## Overview

CacheWarp is a high-performance caching reverse proxy built with **FastAPI** and **Redis**, designed to achieve **90ms P99 latency** and handle **8,000+ RPS** for fintech applications. The initial Week 1 MVP focused on:

- Basic caching for `GET` requests.
- A `/health` endpoint.

Since then, we’ve expanded the system with a two-tier caching architecture, dynamic TTLs, and mock responses for testing, setting a strong foundation for scalability and reliability.

---

## Achievements (Updated as of April 17, 2025)

- **Week 1 MVP (Day 3)**:
  - Successfully implemented caching for `GET` requests.
  - `/health` endpoint operational, providing Redis status.
- **Phase 1 Enhancements**:
  - Implemented a two-tier caching system with L1 (in-memory) and L2 (Redis) caches.
  - Added dynamic TTL calculation based on content type and path patterns (e.g., 30s for `application/json`, 600s for `/static/*`).
  - Introduced mock responses in `origin.py` for testing (e.g., `/static/*` paths return `image/png` content type).
  - Upgraded L1 cache to support per-key TTLs using `cacheout` instead of `cachetools.TTLCache`.

---

## Components

### **1. FastAPI Application (**`src/main.py`**)**

- **Functionality**:

  - Hosts the `/health` endpoint that returns:

    ```json
    {"status": "ok", "redis": "<status>"}
    ```

  - Applies caching middleware for all `GET` requests, bypassing caching for `/health` and `/favicon.ico`.

- **Lifecycle**:

  - Manages Redis connections using `@asynccontextmanager` via FastAPI’s `lifespan` parameter:
    - **Connect on startup**.
    - **Close on shutdown**.

- **Middleware**:

  - Integrates `caching_middleware` to cache responses with a fallback mechanism for errors.

- **Design Choices**:

  - Chose FastAPI for its async support and performance, critical for fintech applications targeting low latency.
  - Used `@asynccontextmanager` to ensure proper resource management, preventing connection leaks.

---

### **2. Configuration (**`src/config.py`**)**

- **Purpose**:
  - Centralized configuration using **Pydantic** (`pydantic-settings`).
- **Fields**:
  - `redis_url`: Redis connection (`RedisDsn`) - Default: `redis://localhost:6379`.
  - `origin_url`: Upstream API (`HttpUrl`) - Default: `http://localhost:8080`.
  - `cache_default_ttl`: Cache Time-to-Live (TTL) - Default: `30 seconds`.
  - `l1_cache_maxsize`: Maximum size of L1 cache - Default: `1000` items.
- **Features**:
  - Support for `.env` files.
  - Case-sensitive environment variables with UTF-8 encoding.
- **Design Choices**:
  - Used Pydantic for type safety and validation, ensuring configuration reliability.
  - Added `l1_cache_maxsize` to control memory usage in the L1 cache, balancing performance and resource constraints.

---

### **3. Cache Layer (**`src/proxy/cache.py`**)**

- **Implementation**:
  - **Two-Tier Caching**:
    - **L1 Cache (In-Memory)**: Uses `cacheout.Cache` with LRU eviction and per-key TTL support.
    - **L2 Cache (Redis)**: Uses an asynchronous Redis client (`redis-py`) with JSON serialization.
- **Methods**:
  - `connect`: Initializes Redis with:
    - **20 max connections**.
    - `decode_responses=True`.
  - `close`: Cleanly closes Redis connections using `aclose()`.
  - `get`: Retrieves data from L1 cache first, falling back to L2 (Redis), and populates L1 on L2 hit using the remaining TTL from Redis.
  - `set`: Stores data in both L1 and L2 caches with a dynamic TTL (default: `30 seconds` if not specified).
- **Features**:
  - Handles connection errors gracefully with logging.
  - Ensures binary safety during Redis data storage.
  - Supports per-key TTLs in L1 cache, aligning expiration with L2.
- **Design Choices**:
  - Adopted `cacheout` over `cachetools.TTLCache` to support per-key TTLs in L1, ensuring consistency with dynamic TTLs in L2.
  - Used a two-tier architecture to optimize performance: L1 for fast in-memory access, L2 for persistence and scalability.
  - Populates L1 on L2 hit with remaining TTL to maintain cache coherence and reduce origin requests.

---

### **4. Caching Middleware (**`src/proxy/middleware.py`**)**

- **Logic**:
  - Caches `GET` responses with:
    - **Status code**: `200`.
    - **Content type**: Varies (e.g., `application/json`, `image/png`).
  - Bypasses caching for `/health` and `/favicon.ico` paths.
- **Flow**:
  1. Checks the cache using `cache.get()`.
  2. If a hit, returns `JSONResponse` with cached data.
  3. On a miss:
     - Fetches from origin using `fetch_origin`.
     - Calculates dynamic TTL based on path and content type.
     - Caches the response in both L1 and L2 with the computed TTL.
     - Returns `JSONResponse` with the origin data.
  4. Handles errors with appropriate status codes (e.g., `404` for “Not found”, `500` for other errors).
- **Robustness**:
  - Validates content type and extracts it from origin response.
  - Handles JSON parsing and connection errors gracefully with logging.
- **Design Choices**:
  - Bypassed caching for `/health` and `/favicon.ico` to ensure accurate health checks and avoid unnecessary caching overhead.
  - Implemented dynamic TTL calculation to optimize cache freshness (e.g., longer TTLs for static assets, shorter for dynamic data).
  - Used `JSONResponse` for consistent response formatting, aligning with fintech API standards.

---

### **5. Origin Fetching (**`src/proxy/origin.py`**)**

- **Implementation**:
  - Uses `aiohttp` for asynchronous HTTP requests to the origin API.
  - Returns a structured response with `content_type` and `data` fields.
- **Mock Responses**:
  - For `/static/*` paths: Returns `{"content_type": "image/png", "data": {"mock_image": true, "path": path}}`.
  - For other paths: Returns `{"content_type": "application/json", "data": {f"mock_response_for_{path}": true, "path": path}}`.
- **Error Handling**:
  - Falls back to mock responses on `ClientConnectorError` for testing purposes.
  - Logs errors and warnings for debugging.
- **Design Choices**:
  - Added mock responses to enable testing without a live origin API, simulating real-world scenarios (e.g., static assets vs. JSON data).
  - Structured responses with `content_type` and `data` to support dynamic TTL calculation based on content type.
  - Used `aiohttp` for its async capabilities, ensuring non-blocking I/O for high throughput.

---

### **6. Dynamic TTL Calculation (**`src/proxy/ttl_calculator.py`**)**

- **Implementation**:
  - Calculates TTL based on:
    - **Path Patterns**: `/static/*` → 600 seconds.
    - **Content Types**: `application/json` → 30 seconds.
- **Features**:
  - Prioritizes path-based rules over content-type rules.
  - Falls back to `settings.cache_default_ttl` (30 seconds) if no rules match.
- **Design Choices**:
  - Implemented dynamic TTLs to optimize cache freshness: longer TTLs for static assets (e.g., images) to reduce origin load, shorter TTLs for dynamic data (e.g., JSON APIs) to ensure freshness.
  - Prioritized path-based rules to handle specific cases like `/static/*`, ensuring flexibility in TTL assignment.

---

### **7. Testing (**`tests/test_proxy.py`**)**

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
- **Design Choices**:
  - Focused on testing the caching flow to ensure reliability of the core feature.
  - Used `pytest-asyncio` to support FastAPI’s async nature, ensuring accurate testing of async middleware and Redis interactions.

---

### **8. Infrastructure (**`docker/docker-compose.yml`**)**

- **Redis**:
  - Image: `redis:7-alpine`.
  - Exposes port `6379`.
  - Includes a healthcheck (`redis-cli ping`) for monitoring.
- **Setup**:
  - Persistent volume: `redis_data`.
  - Lightweight image for efficient deployment.
- **Design Choices**:
  - Chose `redis:7-alpine` for its small footprint and performance, critical for fintech applications.
  - Added a healthcheck to ensure Redis availability, aligning with production best practices.

---

## Design Rationale

- **Two-Tier Caching**: Introduced L1 (in-memory) and L2 (Redis) caches to balance speed and persistence. L1 provides fast access for hot data, while L2 ensures durability and scalability.
- **Dynamic TTLs**: Implemented to optimize cache freshness based on content type and path, reducing origin load for static assets while ensuring fresh dynamic data.
- **Mock Responses**: Added for testing flexibility, allowing development and testing without a live origin API, simulating real-world scenarios.
- **Per-Key TTLs in L1**: Switched to `cacheout` to support per-key TTLs, aligning L1 expiration with L2 and preventing stale data inconsistencies.
- **Async Architecture**: Leveraged FastAPI and `aiohttp` for non-blocking I/O, ensuring high throughput and low latency for fintech workloads.

---

## Conclusion

CacheWarp’s architecture leverages **FastAPI**, **Redis**, and **cacheout** to deliver a robust, scalable caching solution for fintech applications. With its two-tier caching, dynamic TTLs, and modular design, it’s well-positioned for future enhancements like request coalescing and advanced caching strategies (e.g., bulk expiration, ML-based TTL optimization). The project is on track to meet its performance goals of 90ms P99 latency and 8,000+ RPS.