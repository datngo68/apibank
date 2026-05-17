from locust import HttpUser, between, task


class ApiBankUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def health(self) -> None:
        self.client.get("/healthz")
