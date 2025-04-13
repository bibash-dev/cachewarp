# CacheWarp  
**A FastAPI-powered caching proxy built for high-performance APIs.**

---

## **Overview**  
CacheWarp is an intelligent caching proxy system that enhances API performance by reducing latency, offloading server load, and maintaining data freshness. It is designed for modern, fintech-grade applications like payment systems and e-commerce APIs.

---

## **Goals**  
- **Sub-90ms P99 latency** for seamless client interactions  
- **8,000+ requests per second (RPS)** throughput to scale with demand  
- **90%+ cache hit ratio** for optimized efficiency  
- **Fintech-grade reliability**, tailored for critical systems like payment APIs  

---

## **Current Status**  
**Day 1**: Initiating architecture design and system setup.  

**Timeline**:  
- Week 1 (by April 19, 2025): Basic caching with Redis and metrics  
- Week 2: Smart TTL and performance tweaks  
- Week 3: Kubernetes deployment and advanced features  

---

## **Features**  
### **Core Functionalities**  
- **Adaptive TTL Calculation**: Dynamically caches API responses based on endpoint type, reducing redundancy.  
- **Stale-While-Revalidate Support**: Provides immediate responses while asynchronously refreshing data from the origin.  
- **Request Deduplication**: Prevents unnecessary load during cache misses using Redis lock mechanisms.  
- **Comprehensive Observability**: Real-time monitoring with Prometheus and Grafana for metrics like hit ratio and latency.

### **Production-Ready Design**  
- **Two-Layer Caching**:  
  - **L1 (Local Memory)**: For quick access to frequently accessed data using an in-memory cache.  
  - **L2 (Redis)**: Persistent storage for scalable caching solutions.  
- **Fault-Tolerance**: Gracefully handles failures by serving stale data when the origin is unreachable.  
- **High Scalability**: Dockerized and Kubernetes-ready for handling real-world workloads.

---

## **Roadmap**  
- **Week 1**: Implement basic caching and Prometheus metrics  
- **Week 2**: Develop self-tuning TTL, stale-while-revalidate support, and deduplication  
- **Week 3**: Add auto-discovery, circuit breakers, and Kubernetes deployment  
- **Week 4**: Perform benchmarks, create a demo GIF, and polish the portfolio presentation  

---

## **Setup Instructions (Coming Soon)**  
Follow these steps to set up CacheWarp locally. Requires **Python 3.11**.  

```bash
# Step 1: Install dependencies
pip install -r requirements.txt

# Step 2: Start services
docker-compose up -d

# Step 3: Run the FastAPI app
uvicorn app.main:app --reload
