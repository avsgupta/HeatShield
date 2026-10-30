# HeatShield Mumbai — Google Colab
# Run the installation cell first, then run this entire app cell.
# The Gradio app will print a public URL below. Open that URL to use the dashboard.
# Login: user123
# Password: pswrd


import re, html, requests
import numpy as np
import pandas as pd
import gradio as gr
import folium
import plotly.express as px
from datetime import datetime
from shapely.geometry import shape
from pyproj import Geod

# ============================================================
# HEATSHIELD MUMBAI — DECISION-FOCUSED DASHBOARD
# Login: user123 / pswrd
# ============================================================

LOGIN_USER = "user123"
LOGIN_PASSWORD = "pswrd"

BMC_GIS_URL = (
    "https://services8.arcgis.com/r6MmJtuWAzMawmJ8/"
    "arcgis/rest/services/BMConMaps_Nov26gdb/FeatureServer/24/query"
)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
LAT, LON = 19.0760, 72.8777

# Project screening rules, not official IMD thresholds.
ORANGE_TEMP = 37.0
RED_TEMP = 40.0
ORANGE_APPARENT = 40.0
RED_APPARENT = 45.0

GEOD = Geod(ellps="WGS84")
HEADERS = {"User-Agent": "HeatShieldMumbai/1.0"}

# Population estimates used in this project.
# Verify figures against the latest BMC demographic publication.
POPULATION = {
    "A": 193520, "B": 133142, "C": 173800, "D": 362812,
    "E": 411366, "FS": 377567, "FN": 553355, "GS": 395115,
    "GN": 626578, "HE": 582857, "HW": 321722, "KE": 861762,
    "KW": 783107, "PS": 484816, "PN": 984647, "RS": 723007,
    "RC": 588006, "RN": 451199, "L": 943703, "ME": 844854,
    "MW": 430829, "N": 651487, "S": 777977, "T": 357161
}

# ---------- Real BMC ward boundaries ----------

def ward_code(name):
    s = re.sub(r"[^A-Z]", "", str(name).upper())
    for code in sorted(POPULATION, key=len, reverse=True):
        if s == code or s.startswith(code):
            return code
    return None


def fetch_wards():
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson"
    }

    response = requests.get(
        BMC_GIS_URL, params=params, headers=HEADERS, timeout=60
    )
    response.raise_for_status()
    geo = response.json()

    features, rows = [], []

    for f in geo.get("features", []):
        p = f.get("properties", {})
        g = f.get("geometry")

        if not g:
            continue

        geom = shape(g)
        if geom.is_empty:
            continue

        area, _ = GEOD.geometry_area_perimeter(geom)
        area_km2 = abs(area) / 1_000_000

        # The BMC service can expose different name field variants.
        name = next(
            (p[k] for k in [
                "NAME", "name", "WARD", "Ward",
                "WARD_NAME", "ward_name"
            ] if p.get(k) not in (None, "")),
            "Unknown"
        )

        code = ward_code(name)
        pop = POPULATION.get(code) if code else None

        properties = {
            **p,
            "HS_WARD": code or str(name),
            "HS_AREA": round(area_km2, 2)
        }

        features.append({
            "type": "Feature",
            "geometry": g,
            "properties": properties
        })

        rows.append({
            "Ward": code or str(name),
            "WardName": str(name),
            "Area_km2": area_km2,
            "Population2023": pop,
            "Geometry": g
        })

    if not rows:
        raise ValueError("No ward polygons returned by BMC GIS.")

    return rows, {
        "type": "FeatureCollection",
        "features": features
    }


# ---------- Real weather forecast, no API key ----------

def fetch_weather():
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": (
            "temperature_2m,relative_humidity_2m,"
            "apparent_temperature,wind_speed_10m"
        ),
        "daily": (
            "temperature_2m_max,temperature_2m_min,"
            "apparent_temperature_max"
        ),
        "timezone": "Asia/Kolkata",
        "forecast_days": 3
    }

    r = requests.get(WEATHER_URL, params=params, timeout=45)
    r.raise_for_status()
    data = r.json()

    c, d = data["current"], data["daily"]

    w = {
        "ObservedAt": c.get("time", "Not supplied"),
        "Temperature": float(c["temperature_2m"]),
        "Humidity": float(c["relative_humidity_2m"]),
        "Apparent": float(c["apparent_temperature"]),
        "Wind": float(c["wind_speed_10m"]),
        "TodayMax": float(d["temperature_2m_max"][0]),
        "TodayMin": float(d["temperature_2m_min"][0]),
        "TodayApparentMax": float(d["apparent_temperature_max"][0]),
        "ForecastDates": d["time"],
        "ForecastMax": d["temperature_2m_max"],
        "ForecastMin": d["temperature_2m_min"]
    }

    return w


# ---------- Explainable risk and alert calculations ----------

def clamp_score(x, low, high):
    return float(np.clip((x - low) / (high - low) * 100, 0, 100))


def calculate_city_risk(w):
    # Weather severity components, each on a 0-100 scale.
    max_temp_score = clamp_score(w["TodayMax"], 30, 43)
    apparent_score = clamp_score(w["TodayApparentMax"], 30, 48)
    humidity_score = clamp_score(w["Humidity"], 30, 100)

    # Humidity is a contextual indicator, not a stand-alone
    # heat danger measurement.
    weather_score = (
        0.50 * max_temp_score +
        0.35 * apparent_score +
        0.15 * humidity_score
    )

    return round(weather_score, 1), {
        "Maximum temperature": round(max_temp_score, 1),
        "Apparent heat": round(apparent_score, 1),
        "Humidity": round(humidity_score, 1)
    }


def alert_decision(w, score):
    t = w["TodayMax"]
    at = w["TodayApparentMax"]

    # The strongest applicable rule determines the response.
    if t >= RED_TEMP or at >= RED_APPARENT:
        return {
            "level": "RED",
            "colour": "#ef4444",
            "title": "RED ALERT — urgent heat response recommended",
            "reason": (
                f"Forecast maximum is {t:.1f}°C and forecast apparent "
                f"temperature is {at:.1f}°C. The configured severe-heat "
                "rule has been crossed."
            ),
            "actions": [
                "Activate the highest-level heat response available.",
                "Prioritise outdoor workers and people without reliable cooling.",
                "Extend access to water, shade and suitable cooling facilities.",
                "Coordinate health-service readiness and rapid heat-illness response.",
                "Issue a public warning through the authorised municipal channel."
            ]
        }

    if t >= ORANGE_TEMP or at >= ORANGE_APPARENT:
        return {
            "level": "ORANGE",
            "colour": "#f97316",
            "title": "ORANGE ALERT — enhanced precautions recommended",
            "reason": (
                f"Forecast maximum is {t:.1f}°C and forecast apparent "
                f"temperature is {at:.1f}°C. The configured elevated-heat "
                "rule has been crossed."
            ),
            "actions": [
                "Prepare targeted public heat-safety messaging.",
                "Check water availability at busy public places.",
                "Prioritise shade at exposed bus stops and market areas.",
                "Review outdoor-worker exposure and work-rest arrangements.",
                "Alert local health facilities to prepare for heat-related cases."
            ]
        }

    if t >= 34 or score >= 50:
        return {
            "level": "YELLOW",
            "colour": "#eab308",
            "title": "YELLOW WATCH — preventive measures recommended",
            "reason": (
                f"Forecast maximum is {t:.1f}°C. Conditions warrant "
                "monitoring and preventive action under the prototype rules."
            ),
            "actions": [
                "Keep drinking-water access and shaded rest areas available.",
                "Monitor the forecast and local heat complaints.",
                "Prepare public messaging if conditions worsen."
            ]
        }

    return {
        "level": "GREEN",
        "colour": "#22c55e",
        "title": "GREEN — routine monitoring",
        "reason": (
            f"Forecast maximum is {t:.1f}°C and forecast apparent "
            f"temperature is {at:.1f}°C. No prototype heat-alert trigger "
            "has been crossed."
        ),
        "actions": [
            "Maintain normal heat-safety services.",
            "Continue monitoring forecasts and local reports."
        ]
    }


# ---------- Ward exposure score ----------

def calculate_ward_scores(wards, weather_score):
    df = pd.DataFrame([
        {k: v for k, v in w.items() if k != "Geometry"}
        for w in wards
    ])

    df["PopulationDensity"] = (
        df["Population2023"] / df["Area_km2"]
    )

    valid = df["PopulationDensity"].dropna()

    if valid.empty:
        df["RiskScore"] = np.nan
        df["RiskBand"] = "Insufficient data"
        return df

    lo, hi = valid.quantile(.05), valid.quantile(.95)

    if hi <= lo:
        hi = lo + 1

    df["DensityScore"] = (
        (df["PopulationDensity"] - lo) / (hi - lo) * 100
    ).clip(0, 100)

    # Screening score, not a validated health-risk probability.
    df["RiskScore"] = (
        0.65 * weather_score + 0.35 * df["DensityScore"]
    ).round(1)

    def band(s):
        if pd.isna(s):
            return "Insufficient data"
        if s >= 75:
            return "Very high"
        if s >= 60:
            return "High"
        if s >= 40:
            return "Moderate"
        return "Lower"

    df["RiskBand"] = df["RiskScore"].apply(band)

    return df.sort_values("RiskScore", ascending=False)


# ---------- REVISED: detailed ward-specific solutions ----------

def ward_solutions(row, w, alert):
    """
    Solutions adapt to the current alert and the ward's relative
    population-density score. No unmeasured ward conditions are invented.
    """
    immediate = []
    long_term = []

    ward = str(row.get("Ward", "Selected ward"))
    density_score = row.get("DensityScore", np.nan)
    alert_level = alert.get("level", "YELLOW")

    def add_immediate(title, reason, action, measure):
        immediate.append({
            "title": title,
            "reason": reason,
            "action": action,
            "measure": measure
        })

    def add_long(title, research_basis, action, measure):
        long_term.append({
            "title": title,
            "research_basis": research_basis,
            "action": action,
            "measure": measure
        })

    # 1. Immediate response based on citywide alert severity.
    if alert_level == "RED":
        add_immediate(
            "Activate urgent heat-health outreach",
            "The forecast has crossed this prototype's severe-heat threshold. "
            "People who cannot easily avoid heat may need additional support.",
            "Coordinate ward staff, community organisations and health workers "
            "to check on older adults, infants, people with disabilities, people "
            "living alone and residents without reliable cooling. Share clear "
            "information on heat illness and where to seek help.",
            "People contacted, response time, unresolved requests and referrals completed."
        )

        add_immediate(
            "Protect outdoor workers immediately",
            "Construction, sanitation, street vending and other outdoor work "
            "can involve prolonged heat exposure.",
            "Coordinate with employers on drinking water, shaded rest breaks, "
            "buddy checks and a clear escalation process. Where feasible, "
            "reschedule strenuous work away from the hottest hours.",
            "Worksites covered, water availability, breaks delivered and incidents referred."
        )

        add_immediate(
            "Prepare water, shade and safe resting places",
            "People waiting for transport, shopping or accessing services may "
            "be unable to avoid outdoor exposure.",
            "Inspect busy bus stops, markets, queues and community facilities. "
            "Arrange water and temporary shade where feasible. Verify that any "
            "proposed cooling facility is open, accessible and suitable before "
            "directing residents there.",
            "Priority locations inspected, gaps corrected and facility hours verified."
        )

        add_immediate(
            "Coordinate heat-health response",
            "Severe heat warrants preparedness across public health and municipal teams.",
            "Share the forecast and prototype assessment with authorised teams. "
            "Confirm escalation contacts, referral procedures and arrangements "
            "for residents requiring assistance.",
            "Contact lists verified and response arrangements confirmed."
        )

    elif alert_level == "ORANGE":
        add_immediate(
            "Target people with high outdoor exposure",
            "Elevated forecast heat warrants preventive action before conditions worsen.",
            "Prioritise outdoor workers, commuters, street vendors, older residents "
            "and people with limited access to cooling. Share practical advice on "
            "hydration, shade and recognising heat-illness symptoms.",
            "Priority groups reached and support requests resolved."
        )

        add_immediate(
            "Inspect busy outdoor locations",
            "Waiting and walking areas can expose people to heat for extended periods.",
            "Inspect bus stops, market approaches, public queues and other high-use "
            "locations. Identify missing shade, water access and opportunities for rest.",
            "Locations inspected and urgent gaps assigned for correction."
        )

        add_immediate(
            "Prepare local health services",
            "Heat-related illness may require timely assessment and referral.",
            "Contact appropriate health facilities and ward response teams. Review "
            "referral contacts and make public heat-safety information easy to access.",
            "Facilities contacted and referral details checked."
        )

    elif alert_level == "YELLOW":
        add_immediate(
            "Strengthen preventive readiness",
            "The forecast triggers the prototype's watch level, so preventive measures "
            "should be ready before heat increases.",
            "Check water availability and shaded rest areas at selected public sites. "
            "Prepare a simple ward heat-safety message and an escalation contact.",
            "Readiness checks completed and unresolved issues recorded."
        )

        add_immediate(
            "Identify residents who may need support",
            "Citywide averages do not identify every person who may be especially exposed.",
            "Use existing community and health-service networks to share heat-safety "
            "information and identify requests for assistance.",
            "Community contacts reached and support requests followed up."
        )

    else:
        add_immediate(
            "Maintain routine heat protection",
            "The forecast has not crossed the prototype's higher alert thresholds. "
            "This does not guarantee that every location or resident is safe.",
            "Maintain drinking-water access, shaded rest areas and public information. "
            "Continue monitoring the forecast and local reports.",
            "Routine inspections completed and local concerns reviewed."
        )

    # 2. Ward-specific priorities based on relative density.
    # Density does not prove the existence of a local heat hotspot.
    if pd.notna(density_score) and density_score >= 75:
        add_immediate(
            "Ward priority: inspect concentrated public activity",
            f"Ward {ward} is in the highest relative population-density band. "
            "This warrants investigating service demand, not assuming a hotspot.",
            "Start with busy transit approaches, markets, public queues and "
            "community facilities. Confirm footfall and exposure before selecting "
            "permanent intervention sites.",
            "High-use sites audited and urgent service gaps corrected."
        )

        add_long(
            "Develop a neighbourhood cooling-access network",
            "Heat adaptation planning benefits from accessible water, shade, health "
            "support and suitable cooling locations; density alone does not prove a gap.",
            "Map verified water points, health facilities, shaded spaces and suitable "
            "public buildings. Compare their locations and accessibility with population "
            "distribution, then prioritise new facilities only where gaps are confirmed.",
            "Verified access gaps closed, accessibility and actual service use."
        )

        add_long(
            "Create shaded pedestrian and transit corridors",
            "Shade can reduce direct solar exposure for people walking or waiting outdoors.",
            "Audit routes linking transit stops, markets, schools and public services. "
            "At confirmed gaps, assess street trees, shade structures or shaded waiting "
            "areas, subject to available space and utility constraints.",
            "Shaded route length, priority stops with shade and user feedback."
        )

        add_long(
            "Test heat-safe housing improvements",
            "The code does not measure indoor temperatures or identify overheated buildings.",
            "Survey representative homes for roof material, indoor day/night temperature, "
            "ventilation and shading. Select pilot buildings using measured indoor heat.",
            "Indoor temperature before and after, resident comfort, cost per home and uptake."
        )

    elif pd.notna(density_score) and density_score >= 40:
        add_immediate(
            "Ward priority: target exposed public locations",
            f"Ward {ward} falls in the middle relative population-density band. "
            "The most useful intervention depends on local activity and shade.",
            "Inspect selected bus stops, market areas, school approaches and community "
            "facilities. Rank sites by observed footfall, lack of shade and difficulty "
            "avoiding outdoor exposure.",
            "Priority sites inspected and important gaps ranked."
        )

        add_long(
            "Close verified water and cooling-access gaps",
            "The current dataset does not contain a verified facility inventory or access data.",
            "Map water points, suitable public buildings, health facilities and shaded "
            "spaces. Identify underserved locations and propose new services only after "
            "field checks.",
            "Verified access gaps closed, walking access and service use."
        )

        add_long(
            "Pilot shade improvements at priority locations",
            "Shade benefits depend on solar exposure, existing structures, footfall and space.",
            "Compare candidate sites for bus-stop shade, market canopies, street trees or "
            "other suitable structures. Select a small pilot and measure conditions before "
            "and after implementation.",
            "Shade coverage, comparable temperature measurements, costs and user feedback."
        )

    else:
        add_immediate(
            "Ward priority: check distributed access",
            f"Ward {ward} has a lower relative density score, but isolated residents "
            "and local heat exposure may still need attention.",
            "Review access to drinking water, health services and shaded public places. "
            "Use existing community networks to identify people who may be missed by "
            "broad public messaging.",
            "Access issues identified, support requests followed up and groups contacted."
        )

        add_long(
            "Plan a distributed heat-protection network",
            "A distributed service pattern may suit areas where residents and public "
            "facilities are spread out; confirm the local layout first.",
            "Map water points, shaded public spaces and community facilities. Assess "
            "whether smaller, accessible interventions would address verified gaps better "
            "than one central facility.",
            "Coverage of verified access gaps, accessibility and service use."
        )

        add_long(
            "Protect existing trees and shade",
            "Existing mature shade can provide public benefits, but this app does not "
            "measure canopy coverage or tree condition.",
            "Survey public trees and shaded spaces, identify maintenance or safety "
            "concerns, and assess where additional shade is actually needed.",
            "Tree survival and condition, maintained shade coverage and user feedback."
        )

    # 3. Longer-term interventions informed by urban-heat research.
    add_long(
        "Pilot cool roofs and reflective roof surfaces",
        "Urban heat-mitigation research, including modelling for the Mumbai region, "
        "has examined cool roofs and walls. Benefits depend on materials and building type.",
        "Measure roof and indoor temperatures in representative buildings. Pilot suitable "
        "reflective treatments on selected public buildings or homes where the survey "
        "confirms a problem. Check durability, maintenance and glare.",
        "Roof surface temperature, indoor daytime and nighttime temperature, and cost."
    )

    add_long(
        "Measure vegetation and prioritise nature-based cooling",
        "Mumbai climate planning includes vegetation and permeable surfaces; research "
        "shows that greening benefits vary by built form and intervention type.",
        "Use recent satellite land-cover or canopy data followed by site verification. "
        "Assess tree planting, pocket green spaces or permeable surfaces according to "
        "space, soil, utilities, drainage and maintenance capacity.",
        "Canopy and shade coverage, tree survival, maintenance costs and comparable temperatures."
    )

    add_long(
        "Investigate nighttime heat retention",
        "Buildings and paved surfaces can retain heat after sunset, but this app has no "
        "ward-level nighttime temperature measurements.",
        "Record evening and overnight temperatures at representative built-up, shaded "
        "and greener sites. If persistent hotspots are confirmed, investigate roof "
        "reflectance, external shading, ventilation and suitable surface changes.",
        "Nighttime air and indoor temperatures and hours above a selected comfort threshold."
    )

    add_long(
        "Establish ward-level heat monitoring",
        "A single city reference forecast cannot capture every neighbourhood microclimate "
        "or indoor heat exposure.",
        "Deploy calibrated temperature and humidity sensors at representative sites. "
        "Record time, shade, surface type and site conditions; compare measurements with "
        "the city forecast and satellite observations where available.",
        "Data completeness, sensor quality, confirmed hotspots and evaluated interventions."
    )

    tree_note = (
        "The application does not include measured ward-level tree cover or canopy gaps, "
        "so it cannot claim that this ward specifically needs more trees. First map "
        "existing canopy and identify suitable sites. Candidate species for discussion "
        "with local horticulture staff include Neem, Karanj, Jamun, Bakul, Arjun and "
        "Kadamba. Final selection must consider root space, utilities, drainage, coastal "
        "exposure, native suitability, maintenance and long-term survival."
    )

    return immediate, long_term, tree_note


# ---------- Create readable report ----------

def build_report(w, score, components, alert, df):
    lines = [
        "# HeatShield Mumbai — Heat Response Report",
        f"**Generated:** {datetime.now().strftime('%d %b %Y, %H:%M')}",
        f"**Weather observation:** {w['ObservedAt']} (Mumbai local time)",
        "",
        "## Citywide assessment",
        f"- Current air temperature: {w['Temperature']:.1f}°C",
        f"- Forecast maximum today: {w['TodayMax']:.1f}°C",
        f"- Forecast apparent maximum: {w['TodayApparentMax']:.1f}°C",
        f"- Relative humidity: {w['Humidity']:.0f}%",
        f"- Heat screening score: {score}/100",
        f"- Recommended response: {alert['level']}",
        f"- Reason: {alert['reason']}",
        "",
        "## Actions to take now",
        *[f"- {x}" for x in alert["actions"]],
        "",
        "## Ward priority list"
    ]

    for _, r in df.head(10).iterrows():
        lines.append(
            f"- **Ward {r['Ward']}** — score {r['RiskScore']:.1f}/100; "
            f"{r['RiskBand']}; population {r['Population2023']:,.0f}; "
            f"density {r['PopulationDensity']:,.0f}/km²"
            if pd.notna(r["Population2023"]) and pd.notna(r["PopulationDensity"])
            else f"- **Ward {r['Ward']}** — insufficient population match"
        )

    lines += [
        "",
        "## Important limitations",
        "The ward score combines a shared citywide weather score with relative ward population density. It is a preliminary planning indicator, not a validated health-risk probability.",
        "Ward-level satellite temperature, vegetation, vulnerable-population and cooling-access layers are not yet included.",
        "Orange/red labels are HeatShield prototype recommendations based on configurable rules, not official IMD declarations. Validate these rules against municipal protocols before operational use."
    ]

    return "\n".join(lines)


# ---------- Full data load ----------

def load_dashboard():
    try:
        wards, geo = fetch_wards()
        weather = fetch_weather()
        weather_score, components = calculate_city_risk(weather)
        alert = alert_decision(weather, weather_score)
        df = calculate_ward_scores(wards, weather_score)

        # Dashboard summary in plain language.
        summary = f"""
# Mumbai heat situation

<div style="background:{alert['colour']};padding:18px;border-radius:14px;color:#111827">
<h2 style="margin:0;color:#111827">{alert['title']}</h2>
<p style="margin:8px 0 0 0">{alert['reason']}</p>
</div>

## What this means
- **Right now:** {weather['Temperature']:.1f}°C
- **Expected high today:** {weather['TodayMax']:.1f}°C
- **Feels-like heat forecast:** {weather['TodayApparentMax']:.1f}°C
- **Humidity:** {weather['Humidity']:.0f}%
- **Heat screening score:** {weather_score}/100
- **Last observation:** {weather['ObservedAt']}

### What the city should do
""" + "\n".join(f"- {x}" for x in alert["actions"]) + """

*The alert is a HeatShield prototype recommendation, not an official IMD alert.*
"""

        # Risk chart
        chart = px.bar(
            df.sort_values("RiskScore"),
            x="RiskScore", y="Ward", orientation="h",
            color="RiskScore",
            color_continuous_scale=[
                "#2563eb", "#22c55e", "#eab308", "#f97316", "#ef4444"
            ],
            hover_data=["Population2023", "PopulationDensity", "Area_km2"],
            title="Ward screening scores — higher means higher relative priority"
        )

        chart.update_layout(
            template="plotly_white",
            paper_bgcolor="rgba(255,255,255,0)",
            plot_bgcolor="rgba(255,255,255,0)",
            font_family="DM Sans, Arial, sans-serif",
            font_color="#243f5e",
            title_font_color="#122743",
            xaxis=dict(showgrid=True, gridcolor="#e7eef6", zerolinecolor="#d7e3ef"),
            yaxis=dict(showgrid=False, zerolinecolor="#d7e3ef"),
            height=680
        )

        # Real ward map using OpenStreetMap tiles; no map API key.
        score_map = df.set_index("Ward")["RiskScore"].to_dict()
        band_map = df.set_index("Ward")["RiskBand"].to_dict()
        pop_map = df.set_index("Ward")["Population2023"].to_dict()
        density_map = df.set_index("Ward")["PopulationDensity"].to_dict()

        fmap = folium.Map(
            location=[LAT, LON],
            zoom_start=10,
            tiles="OpenStreetMap",
            control_scale=True
        )

        def style(feature):
            code = str(feature["properties"].get("HS_WARD", ""))
            s = score_map.get(code, np.nan)

            if not np.isfinite(s):
                colour = "#64748b"
            elif s >= 75:
                colour = "#ef4444"
            elif s >= 60:
                colour = "#f97316"
            elif s >= 40:
                colour = "#eab308"
            else:
                colour = "#22c55e"

            return {
                "fillColor": colour,
                "color": "#263238",
                "weight": 1.2,
                "fillOpacity": 0.58
            }

        folium.GeoJson(
            geo,
            name="BMC wards",
            style_function=style,
            highlight_function=lambda f: {
                "weight": 3, "color": "#111827", "fillOpacity": .8
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["HS_WARD", "HS_AREA"],
                aliases=["Ward", "Area (km²)"],
                sticky=True
            ),
            popup=folium.GeoJsonPopup(
                fields=["HS_WARD", "HS_AREA"],
                aliases=["Ward", "Area (km²)"]
            )
        ).add_to(fmap)

        folium.Marker(
            [LAT, LON],
            tooltip="Mumbai weather reference point",
            popup=(
                f"Forecast high: {weather['TodayMax']:.1f}°C<br>"
                f"Feels-like high: {weather['TodayApparentMax']:.1f}°C<br>"
                f"HeatShield score: {weather_score}/100"
            ),
            icon=folium.Icon(color="orange", icon="info-sign")
        ).add_to(fmap)

        folium.LayerControl().add_to(fmap)

        legend = """
        <div style="position:fixed;bottom:22px;left:22px;z-index:9999;
        background:darkblue;color:#111827;padding:12px;border-radius:9px;
        box-shadow:0 2px 10px #555;font-size:13px">
        <b>Relative ward priority</b><br>
        <span style="color:#ef4444">■</span> Very high (75+)<br>
        <span style="color:#f97316">■</span> High (60–74)<br>
        <span style="color:#eab308">■</span> Moderate (40–59)<br>
        <span style="color:#22c55e">■</span> Lower (&lt;40)<br>
        <small>Screening score, not official alert status</small>
        </div>
        """

        fmap.get_root().html.add_child(folium.Element(legend))

        # Embed the complete map document in an iframe.
        map_html = fmap.get_root().render()
        map_iframe = (
            '<iframe title="Mumbai ward risk map" '
            'style="width:100%;height:650px;border:0;border-radius:14px" '
            'srcdoc="' + html.escape(map_html, quote=True) + '"></iframe>'
        )

        table = df[[
            "Ward", "Population2023", "Area_km2",
            "PopulationDensity", "RiskScore", "RiskBand"
        ]].copy()

        table.columns = [
            "Ward", "BMC population (2023)", "Area (km²)",
            "People per km²", "Heat screening score", "Priority"
        ]

        table = table.round(1)

        # Forecast graph.
        forecast_df = pd.DataFrame({
            "Date": weather["ForecastDates"],
            "Expected high (°C)": weather["ForecastMax"],
            "Expected low (°C)": weather["ForecastMin"]
        })

        forecast_chart = px.line(
            forecast_df, x="Date",
            y=["Expected high (°C)", "Expected low (°C)"],
            markers=True,
            title="Expected temperature over the next 3 days"
        )

        forecast_chart.update_layout(
            template="plotly_white",
            paper_bgcolor="rgba(255,255,255,0)",
            plot_bgcolor="rgba(255,255,255,0)",
            font_family="DM Sans, Arial, sans-serif",
            font_color="#243f5e",
            title_font_color="#122743",
            xaxis=dict(showgrid=True, gridcolor="#e7eef6", zerolinecolor="#d7e3ef"),
            yaxis=dict(showgrid=True, gridcolor="#e7eef6", zerolinecolor="#d7e3ef")
        )

        report = build_report(weather, weather_score, components, alert, df)

        # Plain-language alert tab.
        alert_text = f"""
# Recommended alert decision

<div style="background:{alert['colour']};padding:18px;border-radius:14px;color:#111827">
<h2 style="margin:0;color:#111827">{alert['title']}</h2>
<p>{alert['reason']}</p>
</div>

## Recommended actions
""" + "\n".join(f"- {x}" for x in alert["actions"]) + """

This is an automated HeatShield recommendation based on the displayed forecast
and configurable project rules. It is not a notice that an official IMD alert
has been issued.
"""

        return (
            summary, chart, map_iframe, table, forecast_chart,
            alert_text, report, df, wards, weather, alert,
            "Updated successfully from live sources."
        )

    except Exception as e:
        msg = f"""
# Unable to refresh data

**Error:** `{type(e).__name__}: {e}`

The dashboard did not replace missing data with invented values.
Try refreshing when the public BMC GIS and weather services are reachable.
"""

        return (
            msg, None,
            "<p>Map unavailable because source data could not be retrieved.</p>",
            pd.DataFrame(), None, msg, msg, pd.DataFrame(), [], {}, {},
            "Data refresh failed."
        )


# ---------- REVISED: Ward assessment display ----------

def assess_ward(code, df, wards, weather, alert):
    if df is None or df.empty or not weather:
        return "Please refresh the dashboard first.", None

    match = df[df["Ward"].astype(str) == str(code)]

    if match.empty:
        return "No matching ward data is available.", None

    row = match.iloc[0]
    immediate, long_term, tree_note = ward_solutions(row, weather, alert)

    pop_text = (
        f"{row['Population2023']:,.0f}"
        if pd.notna(row["Population2023"]) else "Not available"
    )

    density_text = (
        f"{row['PopulationDensity']:,.0f} people/km²"
        if pd.notna(row["PopulationDensity"]) else "Not available"
    )

    score_text = (
        f"{row['RiskScore']:.1f}/100"
        if pd.notna(row["RiskScore"]) else "Not available"
    )

    density_score = row.get("DensityScore", np.nan)

    if pd.notna(density_score) and density_score >= 75:
        density_group = "High relative density"
        density_explanation = (
            "Investigate high-footfall locations, cooling access and shaded "
            "pedestrian routes first. Density is a prioritisation clue, not "
            "proof of a local heat hotspot."
        )
    elif pd.notna(density_score) and density_score >= 40:
        density_group = "Middle relative density"
        density_explanation = (
            "Prioritise targeted site inspections and close verified water, "
            "shade and cooling-access gaps."
        )
    else:
        density_group = "Lower relative density or unavailable"
        density_explanation = (
            "Investigate distributed access and protect existing shade; low "
            "density does not mean low vulnerability."
        )

    def render_immediate(item):
        return (
            f"### {item['title']}\n"
            f"**Why this matters:** {item['reason']}\n\n"
            f"**What to do:** {item['action']}\n\n"
            f"**How to measure success:** {item['measure']}\n"
        )

    def render_long_term(item):
        return (
            f"### {item['title']}\n"
            f"**Research basis:** {item['research_basis']}\n\n"
            f"**Proposed intervention:** {item['action']}\n\n"
            f"**Success indicators:** {item['measure']}\n"
        )

    text = f"""
# Ward {row['Ward']} — Heat Intervention Plan

## Priority score: {score_text}
**Relative priority level:** {row['RiskBand']}

| Indicator | Current value |
|---|---|
| Population estimate (BMC 2023) | {pop_text} |
| Estimated population density | {density_text} |
| Relative density group | {density_group} |
| Current city reference temperature | {weather['Temperature']:.1f}°C |
| Expected maximum today | {weather['TodayMax']:.1f}°C |
| Expected apparent maximum | {weather['TodayApparentMax']:.1f}°C |
| Recommended citywide prototype alert | {alert['level']} |

### What this means for Ward {row['Ward']}

{density_explanation}

The score combines citywide weather conditions with this ward's population
density relative to other mapped wards. It is a planning-screening indicator,
not a validated probability of illness or a measurement of local temperature.

---

# 1. Immediate actions

These actions reflect the current citywide alert and the ward's available
population-density information.

"""

    for item in immediate:
        text += render_immediate(item) + "\n---\n\n"

    text += """
# 2. Long-term interventions

These options should be selected after checking local conditions. They are not
all intended for every ward: field observations should identify which ones
address a real problem in this ward.

"""

    for item in long_term:
        text += render_long_term(item) + "\n---\n\n"

    text += f"""
# 3. Trees and nature-based cooling

{tree_note}

# 4. Monitoring and evaluation plan

After an intervention is implemented, record a baseline and repeat the
measurement under comparable conditions.

- **Heat exposure:** outdoor temperature, surface temperature where available,
  and shaded versus unshaded conditions.
- **Buildings:** indoor daytime and nighttime temperature before and after a
  cool-roof or shading pilot.
- **Public access:** locations with verified water, shade and cooling access,
  including opening hours and accessibility.
- **Implementation:** sites improved, maintenance requirements, cost and
  completion time.
- **Community outcomes:** site use, resident feedback and support requests
  resolved.

# 5. Why this ward has its score

The ward score combines 65% of the citywide weather score with 35% of the
relative ward-density score. Because all wards use the same citywide forecast,
ward differences mainly reflect relative population density.

**Important data limitation:** this version does not measure local satellite
surface temperature, vegetation coverage, vulnerable-population distribution
or cooling-centre access. It therefore does not claim that any of these
conditions are definitely present in Ward {row['Ward']}.
"""

    comp = pd.DataFrame({
        "Factor": [
            "Citywide heat conditions",
            "Relative population density"
        ],
        "Score contribution": [
            .65 * calculate_city_risk(weather)[0],
            .35 * row["DensityScore"]
        ]
    })

    fig = px.bar(
        comp,
        x="Score contribution",
        y="Factor",
        orientation="h",
        color="Score contribution",
        color_continuous_scale=[
            "#22c55e", "#eab308", "#f97316", "#ef4444"
        ],
        title="What contributes to this ward's score"
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0)",
        font_family="DM Sans, Arial, sans-serif",
        font_color="#243f5e",
        title_font_color="#122743",
        xaxis=dict(showgrid=True, gridcolor="#e7eef6", zerolinecolor="#d7e3ef"),
        yaxis=dict(showgrid=False, gridcolor="#e7eef6", zerolinecolor="#d7e3ef")
    )

    return text, fig


# ---------- UI ----------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --page:#f4f7fa; --paper:#fff; --ink:#172c43; --muted:#65788b; --line:#dbe4ec; --blue:#155b91; --deep:#092944; --sun:#ffc45c; --teal:#28a6ad; }
html,body {background:var(--page)!important;}
body,.gradio-container {background:var(--page)!important;color:var(--ink)!important;font-family:'DM Sans',Arial,sans-serif!important;}
.gradio-container {
    width: 100% !important;
    max-width: 100% !important;
    min-height: 100vh !important;
    margin: 0 !important;
    padding: 18px clamp(12px, 2.4vw, 34px) 42px !important;
    box-sizing: border-box !important;
}
h1,h2,h3,h4 {font-family:'Manrope','DM Sans',sans-serif!important;color:var(--ink)!important;letter-spacing:-.55px;}
h1 {font-weight:800!important;} h2 {font-weight:750!important;margin:1.25em 0 .4em!important;}
p,li {color:#4e6378;line-height:1.72;}
/* Weather-site hierarchy: quiet surfaces instead of a wall of cards */
.gradio-container .block {background:transparent!important;border:0!important;border-radius:0!important;box-shadow:none!important;}
.gradio-container .form,.gradio-container .panel {background:transparent!important;border-color:var(--line)!important;}
.gradio-container .tabs {border-bottom:1px solid var(--line)!important;gap:4px!important;}
.gradio-container [role='tab'] {border-radius:0!important;margin:0 8px 0 0!important;padding:13px 12px!important;font-size:13px!important;font-weight:700!important;color:#718397!important;border:0!important;border-bottom:3px solid transparent!important;background:transparent!important;}
.gradio-container [role='tab'][aria-selected='true'] {color:var(--blue)!important;border-bottom:3px solid var(--sun)!important;background:transparent!important;}
.gradio-container button {border-radius:7px!important;font-weight:700!important;transition:background .16s ease,transform .16s ease;}
.gradio-container button:hover {transform:translateY(-1px);}
.gradio-container button.primary {background:var(--blue)!important;color:#fff!important;border:1px solid var(--blue)!important;box-shadow:none!important;}
.gradio-container button.primary:hover {background:#0b3e65!important;}
.gradio-container input,.gradio-container textarea,.gradio-container select,.gradio-container [role='listbox'] {background:#fff!important;color:var(--ink)!important;border:1px solid #cbd8e3!important;border-radius:7px!important;}
.gradio-container input:focus,.gradio-container textarea:focus {border-color:var(--blue)!important;box-shadow:0 0 0 3px rgba(21,91,145,.09)!important;}
.gradio-container table {border:0!important;border-collapse:collapse!important;}
.gradio-container thead {background:#eaf1f6!important;}
.gradio-container th {color:#31516e!important;font-weight:700!important;}
.gradio-container td {border-color:#e2eaf0!important;color:#314b63!important;}
.gradio-container .label-wrap span {color:#526a80!important;}
.gradio-container .wrap .prose {max-width:none!important;}

/* Readability fix: Gradio Markdown content on light surfaces */
.gradio-container .prose,
.gradio-container .prose p,
.gradio-container .prose li,
.gradio-container .prose strong,
.gradio-container .prose b,
.gradio-container .prose em,
.gradio-container .prose blockquote,
.gradio-container .markdown,
.gradio-container .markdown p,
.gradio-container .markdown li,
.gradio-container .markdown strong,
.gradio-container .markdown b {
    color: #263b59 !important;
}
.gradio-container .prose h1,
.gradio-container .prose h2,
.gradio-container .prose h3,
.gradio-container .prose h4,
.gradio-container .markdown h1,
.gradio-container .markdown h2,
.gradio-container .markdown h3,
.gradio-container .markdown h4 {
    color: #172c43 !important;
}
.gradio-container .prose a,
.gradio-container .markdown a {
    color: #155b91 !important;
}
#heatshield-summary {padding:0!important;margin:0!important;}
#heatshield-summary h1 {font-size:clamp(25px,3vw,35px)!important;margin-bottom:7px!important;}
#heatshield-summary h2 {font-size:21px!important;}
#heatshield-summary ul {padding-left:22px;}
footer {display:none!important;}
@media(max-width:700px) {.gradio-container {padding:10px 10px 26px!important;} .gradio-container [role='tab'] {padding:10px 7px!important;margin-right:2px!important;font-size:11px!important;}}
"""

ENGINEERING = """
# Engineering and calculations

## Data sources
- **BMC:** ward polygons and population estimates used in this project.
- **Open-Meteo:** current conditions and three-day forecast for the Mumbai reference point.
- **OpenStreetMap:** map tiles, requiring no separate API key.

## Heat screening score

The citywide weather score is:

`Weather score = 0.50 × maximum-temperature component`
`              + 0.35 × apparent-temperature component`
`              + 0.15 × humidity component`

Each component is normalised to 0–100 using displayed configurable bounds.

The ward score is:

`Ward score = 0.65 × weather score + 0.35 × relative density score`

Density is scaled against the distribution of mapped wards. Scores are
screening indicators, not probabilities of illness.

## Alert rules used by this prototype

- **Red:** forecast maximum temperature ≥ 40°C OR forecast apparent maximum ≥ 45°C.
- **Orange:** forecast maximum temperature ≥ 37°C OR forecast apparent maximum ≥ 40°C.
- **Yellow:** forecast maximum ≥ 34°C OR weather score ≥ 50.
- **Green:** none of the above.

These are configurable project rules, not official IMD criteria or declarations.
They require validation before municipal operational use.

## What the score currently measures

It measures a citywide weather signal combined with relative ward population
density. Because the same weather observation is shared across wards, score
differences largely reflect density.

## Missing data that would improve ward-level accuracy

- Landsat-derived land-surface temperature by ward.
- ESA WorldCover-derived tree-cover and built-up percentages.
- Vulnerable population distribution.
- Verified cooling centres, water points and health facilities.
- Local temperature observations or validated spatial weather estimates.

## Tree recommendations

A low-green-cover finding cannot be made without a measured vegetation layer.
Neem, Karanj, Jamun, Bakul, Arjun and Kadamba are candidate species for local
horticultural review. Final choice depends on soil, space, utilities, drainage,
coastal exposure and maintenance.

## Sources

- BMC demographics: https://portal.mcgm.gov.in/irj/portal/anonymous/qlCivicDemographics
- BMC ward GIS: https://services8.arcgis.com/r6MmJtuWAzMawmJ8/arcgis/rest/services/BMConMaps_Nov26gdb/FeatureServer/24
- Open-Meteo API: https://open-meteo.com/en/docs
- OpenStreetMap: https://www.openstreetmap.org/
"""

with gr.Blocks(
    theme=gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="sky",
        neutral_hue="slate"
    ),
    css=CSS,
    title="HeatShield Mumbai"
) as app:

    gr.HTML("""
    <header style="position:relative;overflow:hidden;margin:0 0 24px;border-radius:4px;background:linear-gradient(112deg,#092944 0%,#104b74 55%,#187b91 100%);color:#fff;">
      <div style="position:absolute;right:-80px;top:-180px;width:520px;height:520px;border:1px solid rgba(173,232,243,.22);border-radius:50%;box-shadow:0 0 0 44px rgba(173,232,243,.045),0 0 0 90px rgba(173,232,243,.03),0 0 0 140px rgba(173,232,243,.02);pointer-events:none;"></div>
      <div style="position:absolute;right:8%;top:24%;width:130px;height:130px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#fff0bd 0%,#ffc45c 42%,rgba(255,196,92,.08) 72%,transparent 74%);opacity:.95;filter:drop-shadow(0 0 30px rgba(255,190,80,.18));"></div>
      <div style="position:relative;padding:25px clamp(20px,3.4vw,46px) 30px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:38px;">
          <div style="display:flex;align-items:center;gap:12px;"><div style="font:800 23px Manrope,Arial,sans-serif;color:#ffc45c;line-height:1;">◒</div><div><div style="font:800 15px Manrope,Arial,sans-serif;letter-spacing:1.1px;color:#fff;">HEATSHIELD <span style="color:#91deeb;">MUMBAI</span></div><div style="font-size:10px;letter-spacing:2px;color:#b8d2e2;margin-top:4px;">URBAN WEATHER &amp; HEAT INTELLIGENCE</div></div></div>
          <div style="font-size:11px;letter-spacing:1.3px;color:#c9e4ee;text-transform:uppercase;">Mumbai · BMC ward outlook</div>
        </div>
        <div style="position:relative;z-index:1;max-width:760px;"><div style="font-size:11px;font-weight:700;letter-spacing:2.2px;color:#9de0e9;text-transform:uppercase;margin-bottom:10px;">Weather, with a wider view</div><div style="font:800 clamp(32px,4.6vw,54px)/1.04 Manrope,Arial,sans-serif;letter-spacing:-2px;color:#fff;">Feel the forecast.<br><span style="color:#ffc45c;">Understand the heat.</span></div><p style="max-width:610px;margin:16px 0 0;color:#d3e5ef;font-size:14px;line-height:1.8;">Mumbai conditions, ward-level heat screening and practical response planning — bringing the daily forecast together with the bigger urban picture.</p></div>
        <div style="display:flex;gap:22px;flex-wrap:wrap;margin-top:28px;padding-top:15px;border-top:1px solid rgba(220,242,249,.19);font-size:10px;letter-spacing:1.4px;color:#d2e7ef;"><span><b style="color:#ffc45c;">01</b> &nbsp; CURRENT CONDITIONS</span><span><b style="color:#ffc45c;">02</b> &nbsp; WARD OUTLOOK</span><span><b style="color:#ffc45c;">03</b> &nbsp; RESPONSE PLANNING</span></div>
      </div>
    </header>
    """)

    state_df = gr.State(pd.DataFrame())
    state_wards = gr.State([])
    state_weather = gr.State({})
    state_alert = gr.State({})

    with gr.Row():
        refresh_btn = gr.Button("Refresh conditions", variant="primary")
        status = gr.Markdown("⏳ **Connecting to live sources…**")

    gr.Markdown("""
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 14px;">
      <span style="padding:7px 12px;border:1px solid #c8e5d9;background:#e5f4ef;
        border-radius:7px;color:#28765d;font-size:12px;">● Live weather</span>
      <span style="padding:7px 12px;border:1px solid #f0dfb8;background:#fff4df;
        border-radius:7px;color:#94651b;font-size:12px;">◆ Ward-level screening</span>
      <span style="padding:7px 12px;border:1px solid #d2e0f2;background:#eaf1fb;
        border-radius:7px;color:#3f6595;font-size:12px;">✦ Evidence-led actions</span>
    </div>
    """)

    with gr.Tabs():
        with gr.Tab("City overview"):
            gr.Markdown("## Mumbai, at a glance\nCurrent conditions, ward screening priorities and the near-term outlook.")
            summary = gr.Markdown(elem_id="heatshield-summary")
            risk_chart = gr.Plot()
            gr.Markdown("## Ward risk map\nExplore mapped BMC wards and their relative screening scores.")
            map_view = gr.HTML()
            gr.Markdown("## Ward comparison")
            ward_table = gr.Dataframe(interactive=False, wrap=True)
            gr.Markdown("## Three-day outlook")
            forecast_chart = gr.Plot()

        with gr.Tab("Ward explorer"):
            gr.Markdown("## Build a ward action plan\nChoose a BMC ward to review its screening score and tailored response options.")
            ward_choice = gr.Dropdown(
                choices=list(POPULATION.keys()),
                value="A",
                label="Choose a ward"
            )
            assess_btn = gr.Button("Generate ward assessment", variant="primary")
            ward_text = gr.Markdown()
            ward_chart = gr.Plot()

        with gr.Tab("Alert centre"):
            gr.Markdown("## Heat response desk\nReview the current prototype alert level and the actions recommended for these forecast conditions.")
            alert_view = gr.Markdown()

        with gr.Tab("Interventions"):
            gr.Markdown("""
    # Cooler neighbourhoods, healthier streets
    <p style="color:#9fb0c7;">A practical menu of immediate readiness steps and longer-term improvements.
    Choose interventions only after local checks confirm the need.</p>

    ### ⚡ Immediate actions
    - 💧 Drinking-water access and shaded rest areas
    - 🧑‍🤝‍🧑 Targeted outreach to people exposed outdoors
    - 🏥 Heat-health preparedness and clear public communication
    - 🚏 Shade at bus stops, markets and walking routes

    ### 🌿 Long-term improvements
    - 🌳 Measure tree-cover gaps before choosing planting locations
    - 🏠 Evaluate cool roofs and shaded pedestrian routes
    - 🧭 Map cooling facilities and compare access with population
    - 📈 Track whether interventions reduce exposure over time

    The Ward Details tab adapts recommendations to the selected ward's available
    population and exposure information. Tree planting is only prioritised after
    a real canopy-gap layer is available.
    """)

        with gr.Tab("Methodology"):
            gr.Markdown(ENGINEERING)

        with gr.Tab("Full report"):
            report_view = gr.Markdown()

    outputs = [
        summary, risk_chart, map_view, ward_table, forecast_chart,
        alert_view, report_view, state_df, state_wards,
        state_weather, state_alert, status
    ]

    def refresh_callback():
        r = load_dashboard()
        return (
            r[0], r[1], r[2], r[3], r[4], r[5], r[6],
            r[7], r[8], r[9], r[10], r[11]
        )

    refresh_btn.click(refresh_callback, outputs=outputs)
    app.load(refresh_callback, outputs=outputs)

    assess_btn.click(
        assess_ward,
        inputs=[
            ward_choice, state_df, state_wards,
            state_weather, state_alert
        ],
        outputs=[ward_text, ward_chart]
    )

app.launch(
    auth=(LOGIN_USER, LOGIN_PASSWORD),
    server_name="127.0.0.1",
    server_port=7862,
    share=True,
    show_error=True
)
