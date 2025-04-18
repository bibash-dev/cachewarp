# CacheWarp Architecture

## Overview

CacheWarp is a high-performance caching reverse proxy built with **FastAPI** and **Redis**, designed to achieve **90ms P99 latency** and handle **8,000+ RPS** for fintech applications. The initial Week 1 MVP focused on:

- Basic caching for `GET` requests.
- A `/health` endpoint.

Since then, we’ve significantly expanded the system with a **two-tier caching architecture (L1 in-memory, L2 Redis)**, **dynamic TTLs**, **request deduplication** using Redis locks, comprehensive **`Cache-Control` header support**, and the **stale-while-revalidate** strategy, establishing a robust foundation for scalability, reliability, and adherence to HTTP caching standards.

---

## Achievements (Updated as of April 19, 2025)

- **Week 1 MVP (Day 3)**:
  - Successfully implemented caching for `GET` requests.
  - `/health` endpoint operational, providing Redis status.
- **Week 2 Enhancements**:
  - Implemented a **two-tier caching system** with:
    - **L1 Cache (In-Memory)**: Utilizes `cacheout` for fast access with LRU eviction and **per-key TTL support**, enhancing performance for frequently accessed data.
    - **L2 Cache (Redis)**: Employs an asynchronous Redis client (`redis-py`) for persistent storage and scalability, using **JSON serialization** for data integrity.
  - Added **dynamic TTL calculation** based on:
    - **Content Type**: Configurable TTLs for different content types (e.g., `application/json`: 30s).
    - **Path Patterns**: Specific TTLs for URL patterns (e.g., `/static/*`: 600s).
    - **Status Codes**: TTLs based on the origin response status (e.g., `200`: 5s, `404`: 10s).
  - Enhanced `origin.py` with **mock responses** for testing various scenarios (e.g., `/static/*` returns `image/png`).
  - Upgraded L1 cache to support per-key TTLs using `cacheout`, ensuring granular control over cache expiration.
  - Implemented **request deduplication** using Redis locks (utilizing a Lua script for atomic release) to prevent cache stampedes during high-concurrency cache misses.
  - Added comprehensive **`Cache-Control` header support** for:
    - `no-cache` and `no-store`: Bypassing the cache to fetch fresh data from the origin.
    - `max-age=<seconds>`: Allowing clients to specify the maximum age of the cached response, overriding server-side TTL.
  - Implemented **stale-while-revalidate** using separate stale keys in Redis. The proxy serves potentially stale data immediately upon TTL expiration and refreshes it in the background using FastAPI's `BackgroundTasks`, improving perceived performance.
  - Improved **error handling** with structured JSON logging for better debugging and unit tests to ensure the reliability of core caching functionalities.

---

## Components

### **1. FastAPI Application (`src/main.py`)**

- **Functionality**:
  - Hosts the `/health` endpoint that returns:
    ```json
    {"status": "ok", "redis": "<status>"}
    ```
  - Applies the `caching_middleware` to all `GET` requests, selectively bypassing caching for `/health`, `/favicon.ico`, and paths in `settings.cache_skip_paths`.
  - Manages global exceptions and `RequestValidationError` with appropriate HTTP status codes and informative JSON responses.
- **Lifecycle**:
  - Manages Redis connections using `@asynccontextmanager` via FastAPI’s `lifespan`:
    - **Connects to Redis on application startup**.
    - **Closes the Redis connection gracefully on shutdown**, preventing resource leaks.
- **Middleware**:
  - Integrates `caching_middleware` to implement the core caching logic, including retrieval, storage, `Cache-Control` handling, and stale-while-revalidate. It falls back to fetching from the origin if the cache is unavailable or encounters errors.
- **Design Choices**:
  - FastAPI chosen for its **async support and high performance**, crucial for the target latency and throughput of fintech applications.
  - `@asynccontextmanager` ensures **proper resource management** for the Redis connection.
  - **Comprehensive exception handling** improves application reliability and provides meaningful error responses.

---

### **2. Configuration (`src/config.py`)**

- **Purpose**:
  - Centralized and type-safe configuration management using **Pydantic** (`pydantic-settings`).
- **Fields**:
  - `redis_url`: Redis connection URI (`RedisDsn`).
  - `origin_url`: Upstream API base URL (`str`).
  - `cache_default_ttl`: Default cache TTL in seconds (`int`).
  - `l1_cache_maxsize`: Maximum number of items in the L1 cache (`int`).
  - `cache_skip_paths`: List of URL paths to bypass caching (`List[str]`).
  - `ttl_by_content_type`: Dictionary mapping content types to their TTLs (`Dict[str, int]`).
  - `ttl_by_path_pattern`: List of dictionaries defining path patterns and their TTLs (`List[Dict[str, str | int]]`).
  - `ttl_by_status_code`: Dictionary mapping HTTP status codes to their TTLs (`Dict[int, int]`).
  - `stale_ttl_offset`: Additional TTL in seconds for storing stale data (`int`).
- **Features**:
  - Loads configuration from **`.env` files**, supporting case-sensitive, UTF-8 encoded variables.
  - **Validates configuration values** for type safety, ensuring application stability.
  - `l1_cache_maxsize` controls the memory footprint of the in-memory cache.
  - **Dynamic TTL rules** allow fine-grained control over cache expiration based on various factors.
  - `stale_ttl_offset` configures how long stale data is kept for the stale-while-revalidate strategy.
- **Design Choices**:
  - Pydantic provides **robust type checking and validation** for configuration.
  - Environment variable support facilitates deployment across different environments.
  - Granular configuration options enable optimization of caching behavior for various scenarios.

---

### **3. Cache Layer (`src/proxy/cache.py`)**

- **Implementation**:
  - **Two-Tier Caching**:
    - **L1 Cache (In-Memory)**: Uses `cacheout.Cache` with **LRU eviction** and **per-key TTLs** for high-speed access to frequently used data.
    - **L2 Cache (Redis)**: Leverages an asynchronous Redis client (`redis-py`) for **persistent storage**, using **JSON serialization** to store complex data structures safely.
  - **Methods**:
    - `connect`: Establishes a connection to the Redis server, configuring **20 max connections** and enabling `decode_responses=True`. It also loads the `SAFE_RELEASE_LOCK_SCRIPT` for atomic lock release.
    - `close`: Gracefully closes the Redis connection using `aclose()`.
    - `get`: Retrieves data from L1 first. On an L1 miss, it fetches from L2, checks for staleness using the stored `set_time` and `ttl`, and populates L1 with the remaining TTL if the data is fresh. It also checks for and returns stale data from a separate key (`stale:<key>`) if the primary key is a miss.
    - `set`: Stores data in both L1 and L2 with the calculated `ttl`. It also stores the data in a separate `stale:<key>` in Redis with an extended TTL (`ttl + settings.stale_ttl_offset`) to support stale-while-revalidate.
    - `acquire_lock`: Attempts to acquire a Redis lock using `SET NX EX` with a default timeout of 10 seconds, returning the lock value on success.
    - `release_lock`: Releases a Redis lock **atomically** using the loaded Lua script, ensuring that only the holder of the lock can release it.
- **Features**:
  - **Graceful handling of Redis connection errors** (`ConnectionError`, `TimeoutError`) with logging.
  - **Stale-while-revalidate support** by storing and retrieving stale data from dedicated keys.
  - **Binary safety** during Redis operations via JSON serialization.
  - **Request deduplication** via atomic Redis locks prevents cache stampedes.
- **Design Choices**:
  - `cacheout` chosen for its **per-key TTL support** in L1, aligning with the dynamic TTL requirements.
  - Two-tier architecture optimizes for both **speed (L1)** and **persistence/scalability (L2)**.
  - Storing stale data separately ensures its availability for the stale-while-revalidate strategy.
  - Atomic lock release with Lua script guarantees **data integrity** during deduplication.

---

### **4. Caching Middleware (`src/proxy/middleware.py`)**

- **Logic**:
  - Intercepts all HTTP requests and applies caching logic specifically to `GET` requests.
  - **Bypasses caching** for paths in `settings.cache_skip_paths` and when the `Cache-Control` header includes `no-cache` or `no-store`.
  - Respects the `Cache-Control: max-age=<seconds>` header from clients, using it as the TTL if provided.
- **Flow**:
  1. Checks if the request path is in the skip list or if `Cache-Control` dictates bypassing.
  2. Attempts to retrieve data from the cache using `cache.get()`.
  3. On a **cache hit** (fresh or stale):
    - If fresh, returns the cached response directly.
    - If stale, returns the stale response and schedules a background refresh task using `BackgroundTasks`.
  4. On a **cache miss**:
    - Acquires a Redis lock using `cache.acquire_lock()` to prevent multiple concurrent requests to the origin (**request deduplication**).
    - If the lock is acquired:
      - Double-checks the cache after acquiring the lock in case another request already populated it.
      - If still a miss, fetches data from the origin using `fetch_origin()`.
      - Calculates the TTL using `calculate_ttl()` and the client's `max-age` if provided.
      - Stores the origin response in the cache using `cache.set()` if the TTL is positive.
      - Returns the origin response.
    - If the lock cannot be acquired (held by another request), it waits briefly and retries the cache. If still a miss, it fetches from the origin.
- **Robustness**:
  - Handles potential `RuntimeError` during cache retrieval (e.g., Redis disconnection) by proceeding to fetch from the origin.
  - Manages errors during origin fetching and JSON parsing.
- **Design Choices**:
  - Skipping specific paths ensures that dynamic or frequently changing endpoints are not cached.
  - Respecting `Cache-Control` aligns with HTTP standards and allows client-driven caching behavior.
  - Stale-while-revalidate improves perceived performance by serving cached data quickly while ensuring eventual consistency.
  - Request deduplication is crucial for preventing origin overload during cache misses under high load.

---

### **5. Origin Fetching (`src/proxy/origin.py`)**

- **Implementation**:
  - Uses `aiohttp`'s `ClientSession` for asynchronous HTTP requests to the upstream API defined in `settings.origin_url`.
  - Returns a dictionary containing the `content_type` from the origin's response headers and the `data` (typically JSON).
- **Mock Responses**:
  - Provides **mock responses** for testing purposes, specifically:
    - `/static/*` paths return a mock `image/png` response.
    - Other paths return a mock `application/json` response.
- **Error Handling**:
  - Handles `ClientResponseError` for HTTP errors from the origin (e.g., 404, 500).
  - Handles `ClientConnectorError` for connection-level errors to the origin by returning mock responses (for development/MVP).
  - Includes general exception handling for unexpected errors during the fetch process.
- **Design Choices**:
  - `aiohttp` is used for its **asynchronous capabilities**, ensuring non-blocking I/O for efficient communication with the origin.
  - Mock responses enable **testing and development without a fully functional origin API**.
  - Structured responses with `content_type` are essential for the dynamic TTL calculation logic.

---

### **6. Dynamic TTL Calculation (`src/proxy/ttl_calculator.py`)**

- **Implementation**:
  - Calculates the Time-to-Live (TTL) in seconds for cache entries based on a prioritized set of rules:
    1. **Path Patterns**: Uses `fnmatch` to match URL paths against defined patterns (e.g., `/static/*` has a longer TTL).
    2. **Status Codes**: Applies TTLs based on the HTTP status code of the origin response (e.g., `200` might have a shorter TTL than static assets).
    3. **Content Types**: Sets TTLs based on the `Content-Type` header of the origin response (e.g., `application/json` might have a different TTL than `text/html`).
  - Falls back to the `settings.cache_default_ttl` if no specific rules match.
- **Features**:
  - **Prioritized rule evaluation** ensures that more specific rules (like path patterns) take precedence.
  - **Flexibility** in defining TTLs based on various characteristics of the response.
- **Design Choices**:
  - Dynamic TTLs optimize cache freshness by setting longer durations for less frequently changing content (like static assets) and shorter durations for more dynamic data.
  - Status code-based TTLs allow for specific caching strategies for different types of responses (e.g., caching `404 Not Found` errors for a short duration to prevent repeated origin requests).

---

### **7. Testing (`tests/test_middleware.py`)**

- **Framework**:
  - Uses `pytest` for writing and running unit tests.
- **Fixtures**:
  - `client`: Provides a `TestClient` instance for making requests to the FastAPI application within the test environment.
- **Test Cases**:
  - `test_cache_control_no_cache`: Verifies that the `Cache-Control: no-cache` header correctly bypasses the cache.
  - `test_cache_control_max_age`: Ensures that the `max-age` directive overrides the server-defined TTL and that stale data is served after the specified time.
  - `test_stale_while_revalidate`: Aims to confirm that stale data is served immediately after the TTL expires and that a background refresh is initiated. (**Note: Currently reported as not fully functional and requires debugging.**)
- **Design Choices**:
  - `pytest` is a widely adopted and feature-rich testing framework for Python.
  - Focused testing of the core caching functionalities (`Cache-Control`, stale-while-revalidate) is crucial for ensuring the reliability of the proxy.
  - Using `TestClient` allows for realistic simulation of HTTP requests within the testing environment.

---

### **8. Infrastructure (Pending `docker/docker-compose.yml`)**

- **Planned Setup**:
  - **Redis**:
    - Image: `redis:7-alpine` (chosen for its lightweight nature).
    - Port: `6379` (standard Redis port).
    - Healthcheck: `redis-cli ping` for basic availability monitoring.
    - Volume: `redis_data` for persistent storage of cached data.
- **Design Choices**:
  - `redis:7-alpine` selected for its **small footprint and performance**, aligning with the application's performance goals.
  - A healthcheck ensures that the Redis container is running and responsive.
  - A persistent volume prevents data loss across container restarts.
  - Dockerization simplifies deployment and ensures consistent environments.

---

## Design Rationale

- **Two-Tier Caching**: Balances **speed (L1)** and **persistence/scalability (L2)**, optimizing for both low latency and high throughput.
- **Dynamic TTLs**: Intelligently manages cache freshness based on content characteristics, reducing origin load and ensuring data relevance.
- **Request Deduplication**: A critical mechanism for high-concurrency scenarios, preventing origin overload during cache misses.
- **Stale-While-Revalidate**: Enhances user experience by providing immediate responses with potentially stale data while ensuring eventual consistency through background updates.
- **`Cache-Control` Support**: Adheres to HTTP standards, allowing clients to influence caching behavior and improving interoperability.
- **Asynchronous Architecture**: Leverages FastAPI and `aiohttp` for non-blocking I/O, maximizing performance for the target workload.
- **Comprehensive Error Handling and Logging**: Improves application stability, debuggability, and operational visibility.

---

## Conclusion

CacheWarp’s architecture, built on **FastAPI**, **Redis**, and `cacheout`, provides a sophisticated caching solution designed for the demanding performance requirements of fintech applications. Its features, including two-tier caching, dynamic TTLs, request deduplication, `Cache-Control` support, and stale-while-revalidate, aim to achieve low latency and high throughput while adhering to HTTP caching best practices. Ongoing development will focus on stabilizing existing features (like stale-while-revalidate), adding comprehensive unit tests, and preparing for production deployment with Docker.