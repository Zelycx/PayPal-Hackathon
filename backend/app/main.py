
from fastapi import FastAPI

from app.api.session import router as session_router
from app.api.paypal import router as paypal_router

app = FastAPI(
    title="AI Financial Companion",
    description="Backend API for our AI Financial Companion",
    version="1.0.0"
)


@app.get("/")
def home():
    return {
        "message": "AI Financial Companion Backend is running!"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }




# Register API routers
app.include_router(session_router)
app.include_router(paypal_router)
