from fastapi import FastAPI

app = FastAPI(title="Medsien Load Balancer Simulation")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
