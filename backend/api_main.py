from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from datetime import datetime
import os

from backend.db import supabase

app = FastAPI(title="Metro Mate API", version="1.0.0")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class BookingRequest(BaseModel):
    from: str
    to: str

class BookingResponse(BaseModel):
    from: str
    to: str
    stations: int
    baseFare: float
    surcharge: float
    totalFare: float

# Helper Functions
def is_peak_hour():
    now = datetime.now()
    hour = now.hour
    return (8 <= hour < 11) or (17 <= hour < 20)

# API Endpoints

@app.get("/")
async def root():
    return {"message": "Metro Mate API"}

@app.get("/stations", response_model=List[str])
async def get_stations():
    """
    Fetch all stations from Supabase
    Return list of station names sorted by line and sequence
    This API will be used to populate dropdown in frontend
    """
    try:
        response = supabase.table("stations").select("*").order("line").order("sequence").execute()
        
        if response.data is None:
            raise HTTPException(status_code=500, detail="Failed to fetch stations")
        
        stations = [station["name"] for station in response.data]
        return stations
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stations: {str(e)}")

@app.post("/book-ticket", response_model=BookingResponse)
async def book_ticket(booking: BookingRequest):
    """
    Book a ticket between two stations with fare calculation
    """
    try:
        # Validation: If same station → return error
        if booking.from == booking.to:
            raise HTTPException(status_code=400, detail="From and to stations cannot be the same")
        
        # Fetch both stations from Supabase
        from_response = supabase.table("stations").select("*").eq("name", booking.from).execute()
        to_response = supabase.table("stations").select("*").eq("name", booking.to).execute()
        
        # Validation: If station not found → return 404
        if not from_response.data:
            raise HTTPException(status_code=404, detail=f"Station '{booking.from}' not found")
        if not to_response.data:
            raise HTTPException(status_code=404, detail=f"Station '{booking.to}' not found")
        
        from_station = from_response.data[0]
        to_station = to_response.data[0]
        
        # Calculate stations count
        if from_station["line"] == to_station["line"]:
            # Same line: stations = absolute difference of sequence
            stations = abs(from_station["sequence"] - to_station["sequence"])
        else:
            # Different line: interchange station = "Agra College"
            interchange_response = supabase.table("stations").select("*").eq("name", "Agra College").execute()
            if not interchange_response.data:
                raise HTTPException(status_code=404, detail="Interchange station 'Agra College' not found")
            
            interchange = interchange_response.data[0]
            
            # stations1 = from → interchange, stations2 = interchange → to
            stations1 = abs(from_station["sequence"] - interchange["sequence"]) if from_station["line"] == interchange["line"] else 0
            stations2 = abs(to_station["sequence"] - interchange["sequence"]) if to_station["line"] == interchange["line"] else 0
            stations = stations1 + stations2
        
        # Fare calculation
        baseFare = 10 + (stations * 5)
        
        # Peak hour logic: 8–11 AM or 5–8 PM, surcharge = 20% of baseFare
        surcharge = baseFare * 0.2 if is_peak_hour() else 0
        totalFare = baseFare + surcharge
        
        # Insert booking into bookings table
        booking_data = {
            "from_station": booking.from,
            "to_station": booking.to,
            "stations": stations,
            "base_fare": baseFare,
            "surcharge": surcharge,
            "total_fare": totalFare
        }
        
        insert_response = supabase.table("bookings").insert(booking_data).execute()
        
        if insert_response.data is None:
            raise HTTPException(status_code=500, detail="Failed to save booking")
        
        # Return response
        return BookingResponse(
            from=booking.from,
            to=booking.to,
            stations=stations,
            baseFare=baseFare,
            surcharge=surcharge,
            totalFare=totalFare
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing booking: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
