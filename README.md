# Jakarta Traffic Scraper

Extracts road network data from OpenStreetMap and scrapes real-time traffic duration data from Google Maps during peak and off-peak hours. Exports results as Shapefiles for GIS analysis.

## Coverage

- **Areas:** Jakarta (configurable — currently Jakarta Utara & Jakarta Barat)
- **Time periods:**
  - Morning peak: 07:00–09:00
  - Off-peak: 10:00–17:00
  - Evening peak: 17:00–20:00

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Quick Test (5 minutes, one period)

```bash
python -m src.main --duration 5m --period peak_am
```

### Full Pipeline (all periods, all routes)

```bash
python -m src.main
```

### CLI Options

| Flag | Description | Example |
|------|-------------|---------|
| `--duration` | Max scraping time per period | `5m`, `30m`, `1h`, `24h` |
| `--routes` | Max routes to generate per area | `10`, `50`, `500` |
| `--period` | Scrape one time period only | `peak_am`, `off_peak`, `peak_pm` |

### Examples

```bash
# Run for 30 minutes, morning peak only
python -m src.main --duration 30m --period peak_am

# Generate only 20 routes, run all periods
python -m src.main --routes 20

# Full 24-hour scrape
python -m src.main --duration 24h
```

### Post-Processing (raw JSON → Shapefile)

After scraping, convert the raw results into a Shapefile enriched with OSM road attributes:

```bash
python scripts/process_to_shp.py
```

This loads the scraped JSON from `data/raw/`, re-downloads the OSM road network, matches each route to its OSM edge, and exports a Shapefile to `data/output/` with road names, types, and averaged speeds per time period.

## How It Works

1. **Extract** — Downloads road network from OpenStreetMap (via `osmnx`)
2. **Generate** — Creates origin-destination route pairs from road intersections
3. **Scrape** — Opens Google Maps in a headless browser, navigates each route, and extracts duration/distance data
4. **Process** — Matches scraped routes back to OSM edges, aggregates speeds per road segment
5. **Export** — Merges traffic data with road geometry and exports as Shapefile

### Data Extraction Strategy

The scraper uses a three-tier approach to extract traffic data from Google Maps:

1. **Network Interception** (primary) — Captures API responses from Google's internal calls
2. **JavaScript Evaluation** (fallback) — Accesses Google's internal state objects
3. **DOM Parsing** (last resort) — Extracts visible text from the page UI (Indonesian locale: `mnt`, `jam`, `km`)

## Output

### Raw Data (saved during scraping)

- `data/raw/{period}_progress.json` — checkpoint file (resumable)
- `data/raw/{period}_results.json` — final results per time period

### Processed Data

Shapefile (`data/output/jakarta_traffic_YYYYMMDD.shp`) with attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `road_id` | String | OSM way identifier |
| `road_name` | String | Street name (e.g. Jalan ...) |
| `road_type` | String | Highway classification (primary, secondary, residential, etc.) |
| `oneway` | String | One-way flag (`yes`, `no`) |
| `length_m` | Float | Segment length in meters |
| `spd_pk_am` | Float | Average speed 07:00–09:00 (km/h) |
| `spd_offpk` | Float | Average speed 10:00–17:00 (km/h) |
| `spd_pk_pm` | Float | Average speed 17:00–20:00 (km/h) |
| `spd_limit` | Float | Posted speed limit (km/h) |
| `geometry` | LineString | Road geometry from OSM |

## Configuration

| File | Purpose |
|------|---------|
| `config/areas.yaml` | Area boundaries (lat/lon bounding boxes) |
| `config/settings.yaml` | Scraping delays, time periods, route limits, output settings |

## Project Structure

```
src/
├── main.py             # Pipeline orchestration + CLI
├── osm_extractor.py    # OpenStreetMap road network download
├── route_generator.py  # Origin-destination pair generation
├── gmaps_scraper.py    # Google Maps scraping (Playwright)
├── data_processor.py   # Speed aggregation + merge with OSM
└── exporter.py         # Shapefile export
scripts/
└── process_to_shp.py   # Post-processing: raw JSON → Shapefile with OSM attributes
config/
├── areas.yaml          # Area boundaries (lat/lon bounding boxes)
└── settings.yaml       # Scraping delays, time periods, route limits
```
