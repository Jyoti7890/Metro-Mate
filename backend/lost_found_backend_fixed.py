from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime
import os
import re
import sys
import bcrypt
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

app = FastAPI(title="Metro Mate Lost & Found API", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# Configure templates
templates = Jinja2Templates(directory="frontend/templates")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models with STRICT validation
class StationInfo(BaseModel):
    name: str
    line: str

class LostItemRequest(BaseModel):
    item_name: str = Field(..., min_length=1, description="Item name is required")
    station_name: str = Field(..., description="Station name is required")
    description: Optional[str] = Field("", description="Item description")
    user_name: str = Field(..., description="User name is required")
    contact: str = Field(..., description="Contact number is required")
    
    @validator('user_name')
    def validate_user_name(cls, v):
        logger.info(f"Validating user_name: {v}")
        # Only alphabets and spaces allowed
        if not re.match(r'^[A-Za-z ]+$', v):
            logger.error(f"Invalid user_name: {v} - contains non-alphabetic characters")
            raise ValueError('Name must contain only alphabets')
        if len(v.strip()) < 2:
            logger.error(f"Invalid user_name: {v} - too short")
            raise ValueError('Name must be at least 2 characters')
        logger.info(f"Valid user_name: {v}")
        return v.strip()
    
    @validator('contact')
    def validate_contact(cls, v):
        logger.info(f"Validating contact: {v}")
        # STRICT validation: exactly 10 digits, only numbers
        if not re.match(r'^[0-9]{10}$', v):
            logger.error(f"Invalid contact: {v} - not exactly 10 digits")
            raise ValueError('Contact must be exactly 10 digits')
        if len(v) != 10:
            logger.error(f"Invalid contact: {v} - length not 10")
            raise ValueError('Contact must be exactly 10 digits')
        logger.info(f"Valid contact: {v}")
        return v
    
    @validator('item_name')
    def validate_item_name(cls, v):
        logger.info(f"Validating item_name: {v}")
        if not v or len(v.strip()) < 1:
            logger.error(f"Invalid item_name: {v} - empty")
            raise ValueError('Item name cannot be empty')
        logger.info(f"Valid item_name: {v}")
        return v.strip()

class FoundItemRequest(BaseModel):
    item_name: str = Field(..., min_length=1, description="Item name is required")
    station_name: str = Field(..., description="Station name is required")
    description: Optional[str] = Field("", description="Item description")
    user_name: str = Field(..., description="User name is required")
    contact: str = Field(..., description="Contact number is required")
    
    @validator('user_name')
    def validate_user_name(cls, v):
        logger.info(f"Validating user_name: {v}")
        # Only alphabets and spaces allowed
        if not re.match(r'^[A-Za-z ]+$', v):
            logger.error(f"Invalid user_name: {v} - contains non-alphabetic characters")
            raise ValueError('Name must contain only alphabets')
        if len(v.strip()) < 2:
            logger.error(f"Invalid user_name: {v} - too short")
            raise ValueError('Name must be at least 2 characters')
        logger.info(f"Valid user_name: {v}")
        return v.strip()
    
    @validator('contact')
    def validate_contact(cls, v):
        logger.info(f"Validating contact: {v}")
        # STRICT validation: exactly 10 digits, only numbers
        if not re.match(r'^[0-9]{10}$', v):
            logger.error(f"Invalid contact: {v} - not exactly 10 digits")
            raise ValueError('Contact must be exactly 10 digits')
        if len(v) != 10:
            logger.error(f"Invalid contact: {v} - length not 10")
            raise ValueError('Contact must be exactly 10 digits')
        logger.info(f"Valid contact: {v}")
        return v
    
    @validator('item_name')
    def validate_item_name(cls, v):
        logger.info(f"Validating item_name: {v}")
        if not v or len(v.strip()) < 1:
            logger.error(f"Invalid item_name: {v} - empty")
            raise ValueError('Item name cannot be empty')
        logger.info(f"Valid item_name: {v}")
        return v.strip()

class ReportResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None

class ReportItem(BaseModel):
    type: str
    item_name: str
    station_name: str
    description: str
    user_name: str
    contact: str
    created_at: str

# Helper Functions
async def validate_station(station_name: str):
    """Check if station exists in stations table"""
    logger.info(f"Validating station: {station_name}")
    try:
        response = supabase.table("stations").select("name").eq("name", station_name).execute()
        if response.data and len(response.data) > 0:
            logger.info(f"Valid station: {station_name}")
            return True
        logger.error(f"Invalid station: {station_name}")
        return False
    except Exception as e:
        logger.error(f"Error validating station {station_name}: {e}")
        return False

async def create_tables():
    """Create tables if they don't exist"""
    try:
        logger.info("Creating tables if they don't exist")
        # Tables will be created via SQL script
        pass
    except Exception as e:
        logger.error(f"Error creating tables: {e}")

# API Endpoints
@app.get("/", response_class=HTMLResponse)
async def root():
    return templates.TemplateResponse(request=Request({"type": "http", "url": "", "headers": {}, "method": "GET"}), name="index.html")

@app.get("/lost-found", response_class=HTMLResponse)
async def lost_found_page(request: Request):
    return templates.TemplateResponse(request=request, name="lost_found.html")

@app.get("/api/stations", response_model=List[StationInfo])
async def get_stations():
    """Fetch all stations from Supabase"""
    logger.info("Fetching stations")
    try:
        response = supabase.table("stations").select("*").order("line").order("sequence").execute()
        
        if response.data is None:
            logger.error("Failed to fetch stations - no data returned")
            raise HTTPException(status_code=500, detail="Failed to fetch stations")
        
        stations = [
            {"name": station["name"], "line": station["line"]} 
            for station in response.data
        ]
        logger.info(f"Successfully fetched {len(stations)} stations")
        return stations
    
    except Exception as e:
        logger.error(f"Error fetching stations: {e}")
        # Return mock stations if database fails
        mock_stations = [
            {"name": "Agra Cantt", "line": "Main Line"},
            {"name": "Sikandra", "line": "Main Line"},
            {"name": "Taj Mahal", "line": "Main Line"},
            {"name": "Fatehpur Sikri", "line": "Main Line"},
            {"name": "Mathura", "line": "Main Line"},
            {"name": "Vrindavan", "line": "Main Line"},
            {"name": "Bharatpur", "line": "Main Line"},
            {"name": "Aligarh", "line": "Main Line"},
            {"name": "Etawah", "line": "Main Line"},
            {"name": "Kanpur", "line": "Main Line"}
        ]
        logger.info("Returning mock stations due to database error")
        return mock_stations

@app.post("/report-lost-item", response_model=ReportResponse)
async def report_lost_item(request: LostItemRequest):
    """Report a lost item with STRICT validation"""
    logger.info(f"Received lost item report request: {request.dict()}")
    
    try:
        # Validate station exists
        station_valid = await validate_station(request.station_name)
        if not station_valid:
            logger.error(f"Invalid station in request: {request.station_name}")
            raise HTTPException(status_code=400, detail="Invalid station selected")
        
        # Insert into lost_items table
        logger.info("Inserting lost item into database")
        lost_item_data = {
            "item_name": request.item_name,
            "station_name": request.station_name,
            "description": request.description,
            "user_name": request.user_name,
            "contact": request.contact
        }
        
        response = supabase.table("lost_items").insert(lost_item_data).execute()
        
        if not response.data:
            logger.error("Failed to insert lost item - no data returned")
            raise HTTPException(status_code=500, detail="Failed to report lost item")
        
        logger.info(f"Successfully inserted lost item: {response.data[0]['id']}")
        return ReportResponse(
            success=True,
            message="Lost item reported successfully",
            data={"item_id": str(response.data[0]["id"])}
        )
    
    except ValueError as e:
        logger.error(f"Validation error in lost item report: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reporting lost item: {e}")
        raise HTTPException(status_code=500, detail=f"Error reporting lost item: {str(e)}")

@app.post("/report-found-item", response_model=ReportResponse)
async def report_found_item(request: FoundItemRequest):
    """Report a found item with STRICT validation"""
    logger.info(f"Received found item report request: {request.dict()}")
    
    try:
        # Validate station exists
        station_valid = await validate_station(request.station_name)
        if not station_valid:
            logger.error(f"Invalid station in request: {request.station_name}")
            raise HTTPException(status_code=400, detail="Invalid station selected")
        
        # Insert into found_items table
        logger.info("Inserting found item into database")
        found_item_data = {
            "item_name": request.item_name,
            "station_name": request.station_name,
            "description": request.description,
            "user_name": request.user_name,
            "contact": request.contact
        }
        
        response = supabase.table("found_items").insert(found_item_data).execute()
        
        if not response.data:
            logger.error("Failed to insert found item - no data returned")
            raise HTTPException(status_code=500, detail="Failed to report found item")
        
        logger.info(f"Successfully inserted found item: {response.data[0]['id']}")
        return ReportResponse(
            success=True,
            message="Found item reported successfully",
            data={"item_id": str(response.data[0]["id"])}
        )
    
    except ValueError as e:
        logger.error(f"Validation error in found item report: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reporting found item: {e}")
        raise HTTPException(status_code=500, detail=f"Error reporting found item: {str(e)}")

@app.get("/my-reports", response_model=List[ReportItem])
async def get_my_reports():
    """Get ALL reports (both lost and found items) - GLOBAL FEED"""
    logger.info("Fetching ALL reports for global feed")
    
    try:
        # Fetch ALL lost items (NO USER FILTER)
        logger.info("Fetching all lost items")
        lost_response = supabase.table("lost_items").select("*").order("created_at", desc=True).execute()
        lost_items = lost_response.data or []
        logger.info(f"Fetched {len(lost_items)} lost items")
        
        # Fetch ALL found items (NO USER FILTER)
        logger.info("Fetching all found items")
        found_response = supabase.table("found_items").select("*").order("created_at", desc=True).execute()
        found_items = found_response.data or []
        logger.info(f"Fetched {len(found_items)} found items")
        
        # Merge and format reports
        all_reports = []
        
        # Add lost items
        for item in lost_items:
            report = {
                "type": "lost",
                "item_name": item.get("item_name", ""),
                "station_name": item.get("station_name", ""),
                "description": item.get("description", ""),
                "user_name": item.get("user_name", ""),
                "contact": item.get("contact", ""),
                "created_at": item.get("created_at", "")
            }
            all_reports.append(report)
            logger.info(f"Added lost report: {item.get('item_name', '')} by {item.get('user_name', '')}")
        
        # Add found items
        for item in found_items:
            report = {
                "type": "found",
                "item_name": item.get("item_name", ""),
                "station_name": item.get("station_name", ""),
                "description": item.get("description", ""),
                "user_name": item.get("user_name", ""),
                "contact": item.get("contact", ""),
                "created_at": item.get("created_at", "")
            }
            all_reports.append(report)
            logger.info(f"Added found report: {item.get('item_name', '')} by {item.get('user_name', '')}")
        
        # Sort by created_at (latest first)
        all_reports.sort(key=lambda x: x["created_at"], reverse=True)
        
        logger.info(f"Returning {len(all_reports)} total reports")
        return all_reports
    
    except Exception as e:
        logger.error(f"Error fetching reports: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching reports: {str(e)}")

# Initialize tables on startup
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Lost & Found backend...")
    await create_tables()
    logger.info("Lost & Found backend started successfully")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
