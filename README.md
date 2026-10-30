HeatShield Mumbai
Urban weather and heat-screening dashboard for Mumbai, India.

HeatShield Mumbai combines live weather forecasts, BMC ward boundaries, and population estimates in an interactive dashboard to help users explore relative heat-screening priorities and practical response options.

Important: HeatShield Mumbai is a prototype planning aid. Its scores are not validated probabilities of heat-related illness, and its alert levels are project-defined rules—not official IMD warnings.

Features:
1. Live weather conditions: Current temperature, apparent temperature, relative humidity, wind speed, and a three-day forecast from Open-Meteo.
2. Ward mapping: Interactive BMC ward boundaries displayed with Folium and OpenStreetMap tiles.
3. Ward screening: A citywide weather score combined with relative ward population density to calculate comparative screening scores.
4. Visual comparisons: Plotly charts for ward priorities and the temperature outlook.
5. Prototype alert centre: Green, yellow, orange, and red response levels with suggested precautionary actions.
6. Ward explorer: Immediate response suggestions and longer-term intervention ideas for a selected ward.
7. Methodology and report views: Explanations of the score, alert rules, data sources, limitations, and a generated heat-response report.
   
Tech stack
- Python
- Gradio
- Requests
- NumPy
- Pandas
- Folium
- Plotly
- Shapely
- pyproj
- Open-Meteo API
- BMC ArcGIS ward GIS service
- OpenStreetMap tiles
  
Getting started (how to run the project):

Option 1: Google Colab
1. Upload the project Python code to Google Colab or paste it into a code cell.
2. Run this installation cell first:
   !pip -q install gradio requests numpy pandas folium plotly shapely pyproj
3. Run the full application code in the next cell.
4. The app starts a Gradio server and requests a share URL. Open the URL to access the dashboard.
5. The current code uses Gradio authentication. Change the example credentials in the source before sharing the project.
   
Option 2: Run locally
1. Install Python (Python 3.10 or newer is a reasonable starting point; use a version compatible with your installed Gradio release).
2. Clone or download this repository.
3. Create and activate a virtual environment:
   macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   Windows PowerShell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
4. Install the dependencies:
   python -m pip install --upgrade pip
   python -m pip install gradio requests numpy pandas folium plotly shapely pyproj
5. Save the application code as app.py and run:
   python app.py
6. Open the local address printed by Gradio in your browser.
The current application is configured with server_name="0.0.0.0", port 7863, and share=True. For local-only use, consider changing the launch configuration to disable public sharing.

Most errors in running arise from occupied ports, simply changing the port number allows the code to run properly without issue.

How the scoring works:
1. Citywide weather score:
Temperature, apparent temperature, and relative humidity are individually scaled to a 0–100 range using configured bounds. The weather score is calculated as:

Weather score =
    0.50 × maximum-temperature component
  + 0.35 × apparent-temperature component
  + 0.15 × humidity component

2. Ward screening score:
Population density is estimated as population divided by ward area. The density component is normalised against the distribution of mapped wards, using the 5th and 95th percentiles as the scaling bounds. The ward score is:

Ward score =
    0.65 × citywide weather score
  + 0.35 × relative population-density score
    
The dashboard groups scores into these prototype bands:
Score	Screening band:
75–100	Very high
60–74.9	High
40–59.9	Moderate
Below 40	Lower

Note: Missing population matches are treated as insufficient data rather than being presented as reliable scores.

1. Prototype alert rules - Level	Configured rule
A. Red: Forecast maximum temperature ≥ 40°C or apparent-temperature maximum ≥ 45°C
B. Orange: Forecast maximum temperature ≥ 37°C or apparent-temperature maximum ≥ 40°C
C. Yellow: Forecast maximum temperature ≥ 34°C or citywide weather score ≥ 50
D. Green:	None of the above rules are triggered

Note: These are configurable project rules and must not be represented as official IMD thresholds or declarations.

Data sources:
1. Open-Meteo: Current conditions and three-day forecast for the Mumbai reference point. See the API documentation.
2. BMC GIS / ArcGIS: Ward boundary geometries from the configured public BMC GIS service.
3. BMC demographics: Population estimates are embedded in the project code. Verify them against the latest authoritative municipal publication before using them for decisions.
4. OpenStreetMap: Basemap tiles used in the interactive ward map.
The dashboard needs internet access to retrieve weather and ward boundary data. If a public service is unavailable, the app may display a refresh error instead of current results.

Limitations and responsible use:
1. All wards currently share the same citywide weather score. Ward score differences are therefore driven mainly by relative population density.
2. The current model does not include ward-level satellite land-surface temperature, measured tree canopy or vegetation, vulnerable-population distribution, indoor temperature, or verified cooling-centre and water-point access.
3. Population estimates and ward-name matching should be checked against authoritative, up-to-date municipal data.
4. Relative population density does not prove that a ward contains a local heat hotspot or that every resident is highly exposed.
5. Recommendations are prompts for investigation and planning. Confirm local conditions, accessibility, feasibility, and costs before implementing an intervention.
6. Do not use this prototype as a substitute for official weather alerts, emergency guidance, clinical advice, or municipal operating procedures.
   
Security note
The source currently contains example login credentials (user123 / pswrd) directly in the code. 
