# main.py
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import ChatRequest, ChatResponse, HealthResponse
from agent import agent
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SHL Assessment Recommender",
    description="Conversational agent for recommending SHL Individual Test Solutions",
    version="1.0.0",
)

# CORS middleware for flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="ok")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process a chat message and return agent response with optional recommendations."""
    start_time = time.time()

    try:
        # Validate input
        if not request.messages:
            raise HTTPException(status_code=400, detail="Messages list cannot be empty")

        if len(request.messages) > 16:  # 8 turns = 16 messages max
            raise HTTPException(status_code=400, detail="Conversation exceeds maximum turn limit")

        # Process through agent
        response = agent.process_chat(request.messages)

        elapsed = time.time() - start_time
        logger.info(
            f"Chat processed in {elapsed:.2f}s | "
            f"Turns: {len(request.messages)} | "
            f"Recommendations: {len(response.recommendations)} | "
            f"EOC: {response.end_of_conversation}"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        elapsed = time.time() - start_time
        logger.info(f"Chat failed after {elapsed:.2f}s")

        # Return a graceful error response instead of 500
        return ChatResponse(
            reply="I apologize, but I'm having trouble processing your request right now. Could you please try again?",
            recommendations=[],
            end_of_conversation=False,
        )


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "SHL Assessment Recommender",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health",
            "chat": "POST /chat",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)