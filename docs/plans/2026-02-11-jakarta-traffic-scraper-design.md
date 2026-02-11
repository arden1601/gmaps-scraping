# Jakarta Traffic Data Scraper Design

**Date:** 2026-02-11
**Area:** Jakarta Utara and Jakarta Barat, Indonesia
**Purpose:** Collect road segment travel time data for peak and off-peak hours

---

## Overview

System to collect traffic speed data for all roads in Jakarta Utara and Jakarta Barat using OpenStreetMap for road network identification and Google Maps scraping for real-time speed data.

**Key Requirements:**
- Travel time data in peak hours (07:00-09:00, 17:00-20:00) and off-peak (10:00-17:00)
- Spatial output as Shapefile
- Road attributes: type (arterial, collector, highway), one-way/two-way, speed
- Coverage: All roads from highway to pedestrian

---

## System Architecture

### 1. Road Network Extractor
- Downloads OpenStreetMap data for Jakarta Utara and Jakarta Barat
- Extracts all road segments with attributes (name, type, one-way, geometry)
- Identifies intersection points as potential route endpoints
- Outputs a clean road network graph with nodes (intersections) and edges (road segments)

### 2. Route Generator
- Analyzes the road network to create optimal route queries
- Generates origin-destination pairs that maximize coverage of all road types
- Prioritizes major arterials while ensuring local roads are sampled
- Creates a queue of routes to query at each time period

### 3. Google Maps Scraper
- Headless browser (Playwright) with anti-detection measures
- Schedules queries at specific times (peak morning 07-09, peak evening 17-20, off-peak 10-17)
- Extracts travel time and distance from Google Maps directions response
- Implements delays and retry logic to avoid blocking
- Uses Indonesian IP proxies for better targeting

### 4. Data Processor & Exporter
- Combines OSM road attributes with scraped speed/travel time data
- Calculates average speeds by time period for each road segment
- Generates Shapefile with spatial geometry and attribute table
- Validates data quality and flags anomalies

---

## Data Flow

### Phase 1: Network Preparation (One-Time)
```
OSM Overpass API → Road Network Parser → Graph Structure
                                              ↓
                                      Route Queue Generator
```

### Phase 2: Traffic Data Collection (Scheduled)
```
Scheduler → Route Queue → Scraper Workers → Raw Responses
                                ↓                         ↓
                         (Peak 07-09)              Travel Time
                         (Off-peak 10-17)         Distance Data
                         (Peak 17-20)
                                ↓
                        Data Storage (JSON/DB)
```

### Phase 3: Data Processing & Export
```
Raw Data → Speed Calculator → Attribute Joiner → Shapefile Export
```

---

## Technology Stack

| Component | Library | Purpose |
|---|---|---|
| **OSM Data** | `osmnx`, `overpy` | Download and parse OpenStreetMap road networks |
| **Routing** | `networkx` | Graph operations and route pathfinding |
| **Scraping** | `playwright` | Headless browser automation with anti-detection |
| **Proxies** | `scrapy-rotating-proxies` | Residential proxy rotation |
| **Geospatial** | `geopandas`, `shapely` | Spatial data processing and Shapefile export |
| **Scheduling** | `apscheduler` | Time-based task scheduling |
| **Storage** | `sqlite3` | Store intermediate data and raw responses |
| **Config** | `pydantic` | Configuration management |

---

## Scraping Implementation

**Browser Setup:**
- Headless Chromium with stealth plugins
- User agent rotation
- Browser fingerprint randomization
- Cookie and localStorage cleared between sessions

**Anti-Detection Measures:**
- Random delays between 2-10 seconds per query
- Residential Indonesian proxies (rotating every 50-100 requests)
- Mouse movement simulation on initial page load
- Limit concurrent workers (2-3 browsers max)
- Session rotation every 200 queries

**Data Extraction:**
Target `duration_in_traffic` field from Google Maps directions API response:
```json
{
  "routes": [{
    "duration_in_traffic": {"value": 2700},
    "distance": {"value": 12000}
  }]
}
```

---

## Output Schema

**Shapefile Attribute Table:**

| Field Name | Type | Description | Source |
|---|---|---|---|
| `road_id` | String | Unique OSM way identifier | OSM |
| `road_name` | String | Street name | OSM |
| `road_type` | String | highway tag (motorway, primary, secondary, residential, service) | OSM |
| `oneway` | String | 'yes', 'no', or '-1' | OSM |
| `length_m` | Float | Segment length in meters | OSM |
| `speed_peak_am` | Float | Average speed km/h (07:00-09:00) | GMaps |
| `speed_offpeak` | Float | Average speed km/h (10:00-17:00) | GMaps |
| `speed_peak_pm` | Float | Average speed km/h (17:00-20:00) | GMaps |
| `speed_limit` | Float | Posted speed limit km/h | OSM |
| `geometry` | LineString | Spatial geometry of road segment | OSM |

**Projection:** EPSG:3857 (Web Mercator) or EPSG:32748 (UTM Zone 48S)

---

## Error Handling

| Failure Mode | Detection | Recovery Strategy |
|---|---|---|
| IP blocked | HTTP 403/429, CAPTCHA | Rotate proxy, back off 5-15 min |
| Invalid response | Missing fields | Retry up to 3x, flag for review |
| Browser crash | Playwright timeout | Restart browser, resume from checkpoint |
| Rate limit | "Too many requests" | Pause, resume in off-peak hours |

**Checkpoint System:**
- Progress saved every 50 successful queries
- State file tracks completed routes and current offset
- Resume capability after interruption

---

## Execution Timeline

| Step | Description | Duration |
|---|---|---|
| 1 | OSM Network Extraction | Day 1 |
| 2 | Scraper Development & Testing | Days 2-3 |
| 3 | Pilot Run (200 routes) | Day 4 |
| 4 | Full Data Collection | Days 5-7 |
| 5 | Data Processing & Export | Day 8 |

**Total: ~1 week**

---

## Project Structure

```
gmaps-scraping/
├── config/
│   ├── areas.yaml          # Jakarta boundary coordinates
│   └── settings.yaml       # Scraping parameters
├── src/
│   ├── osm_extractor.py   # Download and parse OSM data
│   ├── route_generator.py # Build route queue
│   ├── gmaps_scraper.py   # Main scraper with Playwright
│   ├── data_processor.py  # Merge and calculate speeds
│   └── exporter.py        # Generate Shapefile
├── data/
│   ├── raw/               # Raw scraper responses
│   ├── processed/         # Intermediate processed data
│   └── output/            # Final Shapefiles
└── requirements.txt
```

---

## Cost Considerations

**One-Time Execution Infrastructure Costs:**
- Server (1 week): $5-15
- Proxies (1 week): $30-100
- Captcha solving: $10-50
- **Total: ~$45-165** (no API costs)
