from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import supabase
from pydantic import BaseModel
from typing import List, Optional

try:
    from backend.settings import load_supabase_settings
except ImportError:
    from settings import load_supabase_settings

app = FastAPI(title="Metro Mate Booking API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class NearbyPlace(BaseModel):
    id: str
    name: str
    description: str
    station_name: str
    distance_km: float
    category: str
    rating: float
    image_url: str

# Supabase configuration
SUPABASE_URL, SUPABASE_KEY = load_supabase_settings()

# Initialize Supabase client
def get_supabase_client():
    try:
        return supabase.create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error creating Supabase client: {e}")
        return None

@app.get("/nearby-places", response_model=List[NearbyPlace])
async def get_nearby_places():
    """
    Get all nearby places from the database.
    Returns image_url exactly as stored (complete Supabase URLs).
    """
    try:
        supabase_client = get_supabase_client()
        if not supabase_client:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        # Fetch data from nearby_places table
        response = supabase_client.table("nearby_places")\
            .select("*")\
            .order("rating", desc=True)\
            .execute()
        
        if response.data is None:
            return []
        
        # Convert to response model - image_url is returned exactly as stored
        places = []
        for place in response.data:
            places.append(NearbyPlace(
                id=str(place["id"]),
                name=place["name"],
                description=place["description"],
                station_name=place["station_name"],
                distance_km=float(place["distance_km"]),
                category=place["category"],
                rating=float(place["rating"]),
                image_url=place["image_url"]  # Return exactly as stored - complete URL
            ))
        
        return places
        
    except Exception as e:
        print(f"Error fetching nearby places: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch nearby places: {str(e)}")

@app.get("/nearby-places/{place_id}", response_model=NearbyPlace)
async def get_nearby_place_details(place_id: str):
    """
    Get detailed information about a specific nearby place.
    """
    try:
        supabase_client = get_supabase_client()
        if not supabase_client:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        # Fetch specific place
        response = supabase_client.table("nearby_places")\
            .select("*")\
            .eq("id", place_id)\
            .execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Place not found")
        
        place = response.data[0]
        return NearbyPlace(
            id=str(place["id"]),
            name=place["name"],
            description=place["description"],
            station_name=place["station_name"],
            distance_km=float(place["distance_km"]),
            category=place["category"],
            rating=float(place["rating"]),
            image_url=place["image_url"]  # Return exactly as stored
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching place details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch place details: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Metro Mate Booking API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
