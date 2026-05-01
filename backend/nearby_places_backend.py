from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from db import supabase
    logger.info("Successfully connected to Supabase")
except ImportError:
    logger.error("Could not import db.py. Make sure db.py exists in backend directory.")
    supabase = None

# Initialize FastAPI app
app = FastAPI(title="Metro Mate Nearby Places API", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# Configure templates
templates = Jinja2Templates(directory="frontend/templates")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class NearbyPlace(BaseModel):
    id: str
    name: str
    description: str
    station_name: str
    distance_km: float
    category: str
    rating: float
    image_url: str
    created_at: str

class NearbyPlaceResponse(BaseModel):
    id: str
    name: str
    description: str
    station_name: str
    distance_km: float
    category: str
    rating: float
    image_url: str

# Helper Functions
async def validate_station(station_name: str) -> bool:
    """Check if station exists in stations table"""
    try:
        response = supabase.table("stations").select("name").eq("name", station_name).execute()
        if response.data and len(response.data) > 0:
            logger.info(f"Valid station: {station_name}")
            return True
        logger.warning(f"Invalid station: {station_name}")
        return False
    except Exception as e:
        logger.error(f"Error validating station {station_name}: {e}")
        return False

def format_place_data(place_data: dict) -> dict:
    """Format place data for response"""
    return {
        "id": str(place_data.get("id", "")),
        "name": place_data.get("name", ""),
        "description": place_data.get("description", ""),
        "station_name": place_data.get("station_name", ""),
        "distance_km": float(place_data.get("distance_km", 0.0)),
        "category": place_data.get("category", ""),
        "rating": float(place_data.get("rating", 0.0)),
        "image_url": place_data.get("image_url", ""),
        "created_at": place_data.get("created_at", "")
    }

# API Endpoints
@app.get("/", response_class=HTMLResponse)
async def root():
    return templates.TemplateResponse(
        request=Request({"type": "http", "url": "", "headers": {}, "method": "GET"}), 
        name="index.html"
    )

@app.get("/nearby-places", response_model=List[NearbyPlaceResponse])
async def get_nearby_places(station: Optional[str] = Query(None, description="Filter by station name")):
    """
    Get nearby places.
    If station is provided, filter by station_name.
    Otherwise, return all places.
    """
    logger.info(f"Fetching nearby places for station: {station}")
    
    try:
        if station:
            # Validate station exists
            if not await validate_station(station):
                raise HTTPException(status_code=400, detail="Invalid station name")
            
            # Filter by station
            response = supabase.table("nearby_places").select("*").eq("station_name", station).order("rating", desc=True).execute()
            places_data = response.data or []
            logger.info(f"Found {len(places_data)} places for station: {station}")
        else:
            # Get all places
            response = supabase.table("nearby_places").select("*").order("rating", desc=True).execute()
            places_data = response.data or []
            logger.info(f"Found {len(places_data)} total places")
        
        if not places_data:
            logger.info("No nearby places found")
            raise HTTPException(status_code=404, detail="No nearby places found")
        
        # Format response data
        formatted_places = []
        for place in places_data:
            formatted_place = format_place_data(place)
            formatted_places.append(NearbyPlaceResponse(**formatted_place))
        
        logger.info(f"Returning {len(formatted_places)} formatted places")
        return formatted_places
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching nearby places: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching nearby places: {str(e)}")

@app.get("/nearby-places/{place_id}", response_model=NearbyPlaceResponse)
async def get_nearby_place_details(place_id: str):
    """
    Get detailed information about a specific nearby place.
    """
    logger.info(f"Fetching details for place ID: {place_id}")
    
    try:
        # Get place by ID
        response = supabase.table("nearby_places").select("*").eq("id", place_id).execute()
        places_data = response.data or []
        
        if not places_data:
            logger.warning(f"Place not found: {place_id}")
            raise HTTPException(status_code=404, detail="Place not found")
        
        # Format and return place data
        place_data = places_data[0]
        formatted_place = format_place_data(place_data)
        
        logger.info(f"Returning details for place: {formatted_place.get('name', 'Unknown')}")
        return NearbyPlaceResponse(**formatted_place)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching place details: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching place details: {str(e)}")

@app.get("/api/stations", response_model=List[dict])
async def get_stations():
    """Get all stations for dropdown"""
    logger.info("Fetching stations for dropdown")
    
    try:
        response = supabase.table("stations").select("*").order("line").order("sequence").execute()
        
        if response.data is None:
            logger.error("Failed to fetch stations")
            raise HTTPException(status_code=500, detail="Failed to fetch stations")
        
        stations = [{"name": station["name"]} for station in response.data]
        logger.info(f"Returning {len(stations)} stations")
        return stations
    
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching stations: {str(e)}")

@app.get("/nearby-places", response_class=HTMLResponse)
async def nearby_places_page(request: Request):
    """Serve the nearby places page"""
    return templates.TemplateResponse(request=request, name="nearby_places.html")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Nearby Places backend...")
    logger.info("Nearby Places backend started successfully")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server for Nearby Places...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
