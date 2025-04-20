from prometheus_client import Counter, Histogram, Gauge

from src.logging import logger

# --- Prometheus Metrics Definition ---

# Cache Hit Counter:
# We're using a Counter here to track the total number of times our cache successfully served a request.
# The 'cache_layer' label helps us differentiate whether the hit occurred in our fast in-memory cache (L1)
# or our distributed Redis cache (L2). This is super useful for understanding our cache performance at each level.
cache_hits_total = Counter(
    "cachewarp_cache_hits_total",
    "Total number of cache hits",
    ["cache_layer"]  # Label to distinguish between L1 and L2
)

# Cache Miss Counter:
# Similarly, this Counter tracks every time our cache couldn't find the requested data
# and had to fetch it from the origin server. The 'cache_layer' label again tells us
# if the miss happened in L1 or L2, which is crucial for identifying areas for optimization.
cache_misses_total = Counter(
    "cachewarp_cache_misses_total",
    "Total number of cache misses",
    ["cache_layer"]
)

# Request Latency Histogram:
# This Histogram is vital for monitoring the responsiveness of our caching proxy.
# It records the duration it takes to process each request from start to finish.
# The 'buckets' define the ranges of latency we're interested in. We've updated these
# to provide finer-grained insights into the typical response times and any outliers.
request_latency_seconds = Histogram(
    "cachewarp_request_latency_seconds",
    "Request latency in seconds",
    buckets=[0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]  # Updated buckets for better granularity
)

# Total Requests Counter:
# A simple counter to keep track of the total number of requests our proxy has handled.
# This is a fundamental metric for understanding the traffic volume our service is managing.
requests_total = Counter(
    "cachewarp_requests_total",
    "Total number of requests processed"
)

# Circuit Breaker State Gauge:
# This Gauge reflects the current state of our circuit breaker.
# We're using numerical values (0 for CLOSED, 1 for OPEN, 2 for HALF_OPEN) for easy monitoring.
# The circuit breaker helps prevent cascading failures by stopping requests to the origin
# when it's unhealthy.
circuit_breaker_state = Gauge(
    "cachewarp_circuit_breaker_state",
    "Current state of the circuit breaker (0=CLOSED, 1=OPEN, 2=HALF_OPEN)"
)

# Redis Error Counter:
# This Counter tracks the total number of errors we encounter while interacting with our Redis cache.
# The 'error_type' label provides specific information about the kind of Redis error (e.g., connection issues, timeouts),
# which is essential for diagnosing and fixing problems with our caching layer.
redis_errors_total = Counter(
    "cachewarp_redis_errors_total",
    "Total number of Redis errors",
    ["error_type"]  # Label for ConnectionError, TimeoutError, etc.
)

# Origin Error Counter:
# This Counter records the total number of times we fail to fetch data from the origin server.
# The 'error_type' label helps us understand the nature of these failures (e.g., network issues, server errors),
# allowing us to better understand the reliability of our backend.
origin_errors_total = Counter(
    "cachewarp_origin_errors_total",
    "Total number of origin fetch errors",
    ["error_type"]
)

# --- Helper Function for Logging Metric Recording Errors ---
def log_metrics_error(metric_name: str, error: Exception) -> None:
    """
    Logs an error if there's an issue with recording a metric.
    This is a defensive measure to ensure that if Prometheus is temporarily unavailable
    or there's an unexpected issue with the client library, it doesn't crash our main application.
    We log the error with traceback for detailed debugging.

    Args:
        metric_name (str): Name of the metric that failed to record.
        error (Exception): The specific exception that occurred during recording.
    """
    logger.error(f"Failed to record metric {metric_name}: {str(error)}", exc_info=True)

# --- Helper Functions to Record Specific Metrics Safely ---
def record_cache_hit(cache_layer: str) -> None:
    """
    Records a cache hit for the specified cache layer (L1 or L2).
    """
    try:
        cache_hits_total.labels(cache_layer=cache_layer).inc()
    except Exception as e:
        log_metrics_error("cache_hits_total", e)

def record_cache_miss(cache_layer: str) -> None:
    """
    Records a cache miss for the specified cache layer (L1 or L2).
    """
    try:
        cache_misses_total.labels(cache_layer=cache_layer).inc()
    except Exception as e:
        log_metrics_error("cache_misses_total", e)

def observe_request_latency(duration: float) -> None:
    """
    Records the latency of a request in seconds.
    This function takes the duration of the request processing and adds it to the histogram,
    allowing Prometheus to calculate percentiles and other statistical measures of our latency.
    """
    try:
        request_latency_seconds.observe(duration)
    except Exception as e:
        log_metrics_error("request_latency_seconds", e)  # Fixed typo

def record_request() -> None:
    """
    Records a processed request.
    Each time a request is successfully handled by our proxy, we increment this counter
    to track the overall throughput.
    """
    try:
        requests_total.inc()
    except Exception as e:
        log_metrics_error("requests_total", e)

def set_circuit_breaker_state(state: str) -> None:
    """
    Sets the current state of the circuit breaker.
    We map the string representation of the state (e.g., "CLOSED") to its numerical equivalent
    before setting the Gauge. A default of 0 (CLOSED) is used if an invalid state is provided.
    """
    state_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
    try:
        circuit_breaker_state.set(state_map.get(state, 0))
    except Exception as e:
        log_metrics_error("circuit_breaker_state", e)

def record_redis_error(error_type: str) -> None:
    """
    Records a Redis error with a specific type (e.g., "ConnectionError").
    The 'error_type' label allows us to categorize Redis issues for better analysis.
    """
    try:
        redis_errors_total.labels(error_type=error_type).inc()
    except Exception as e:
        log_metrics_error("redis_errors_total", e)

def record_origin_error(error_type: str) -> None:
    """
    Records an error when fetching from the origin server, with a specific type.
    The 'error_type' label helps us understand the reasons for origin fetch failures.
    """
    try:
        origin_errors_total.labels(error_type=error_type).inc()
    except Exception as e:
        log_metrics_error("origin_errors_total", e)