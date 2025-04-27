from locust import HttpUser, task, between
from locust.env import Environment
from locust.log import setup_logging

# Set up logging for locust
setup_logging("INFO")

class CacheWarpUser(HttpUser):
    # Wait time between requests for each user (simulates realistic user behavior)
    wait_time = between(0.1, 0.5)  # Wait between 0.1 and 0.5 seconds

    # Host to test (set via --host command-line argument)
    host = "http://localhost:8000"

    @task
    def fetch_image(self):
        # Send a GET request to /static/image1.png
        # name="fetch_image" groups these requests in the Locust UI
        with self.client.get(
            "/static/image1.png",
            headers={"Accept": "image/png"},
            name="fetch_image",
            catch_response=True
        ) as response:
            # Verify the response status and Content-Type
            if response.status_code != 200:
                response.failure(f"Unexpected status code: {response.status_code}")
            elif response.headers.get("content-type") != "image/png":
                response.failure(f"Unexpected Content-Type: {response.headers.get('content-type')}")
            else:
                response.success()

def run_locust():
    # Create a Locust environment
    env = Environment(user_classes=[CacheWarpUser])
    env.create_local_runner()

    # Start the test with 10 users, spawning 1 user per second
    env.runner.start(user_count=10, spawn_rate=1)

    # Run the test for 1 minute (60 seconds)
    import time
    time.sleep(60)

    # Stop the test
    env.runner.quit()

# if __name__ == "__main__":
#     run_locust()