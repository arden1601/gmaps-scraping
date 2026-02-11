# Jakarta Traffic Scraper

Extracts road network data from OpenStreetMap and scrapes Google Maps for traffic speed data during peak and off-peak hours.

## Coverage

- **Areas:** Jakarta Utara and Jakarta Barat, Indonesia
- **Time periods:**
  - Morning peak: 07:00-09:00
  - Off-peak: 10:00-17:00
  - Evening peak: 17:00-20:00

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Full Pipeline

```python
python -m src.main
```

### Individual Components

```python
from src.osm_extractor import OSMExtractor
from src.gmaps_scraper import GMapsScraper
```

## Output

Shapefile with attributes:
- `road_id`: OSM way identifier
- `road_name`: Street name
- `road_type`: Highway classification
- `oneway`: One-way flag
- `speed_peak_am`: Average speed 07:00-09:00
- `speed_off_peak`: Average speed 10:00-17:00
- `speed_peak_pm`: Average speed 17:00-20:00
- `speed_limit`: Posted speed limit
- `geometry`: LineString geometry

## Configuration

Edit `config/areas.yaml` for area boundaries and `config/settings.yaml` for scraping parameters.
