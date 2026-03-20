"""
Appraisal Tool v3
A Streamlit app for generating STR property appraisals.
Features: Geocoding, property lookup, Airbnb research, map display.
"""

import streamlit as st
import pymssql
import requests
import os
import math
import json
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_CONFIG = {
    "server": os.getenv("DB_SERVER", "bnbme-fuse.database.windows.net"),
    "user": os.getenv("DB_USER", "fuse"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "fuseanalytics"),
    "port": 1433
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
REGIONS = ["Wagga Wagga", "Orange", "Bathurst", "Dubbo"]

# LTR weekly rental estimates by region and bedrooms
LTR_ESTIMATES = {
    "Wagga Wagga": {2: 380, 3: 450, 4: 550, 5: 650},
    "Orange": {2: 350, 3: 420, 4: 500, 5: 600},
    "Bathurst": {2: 360, 3: 430, 4: 520, 5: 620},
    "Dubbo": {2: 340, 3: 400, 4: 480, 5: 580},
}

# =============================================================================
# PAGE CONFIG & STYLING
# =============================================================================

st.set_page_config(
    page_title="Appraisal Tool",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');
    
    * { font-family: 'DM Sans', sans-serif; }
    .stApp { background: linear-gradient(180deg, #F0F4F8 0%, #FFFFFF 100%); }
    h1 { color: #1E3A5F !important; font-weight: 700 !important; }
    h2, h3 { color: #2D5A87 !important; font-weight: 600 !important; }
    
    .stButton > button {
        background: linear-gradient(135deg, #3B82F6 0%, #1E40AF 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 600;
        border-radius: 8px;
    }
    
    .metric-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-left: 4px solid #3B82F6;
        margin: 0.5rem 0;
    }
    
    .comp-card {
        background: white;
        border-radius: 12px;
        padding: 1.25rem;
        margin: 0.75rem 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        border-left: 4px solid #10B981;
    }
    
    .comp-card.top-performer {
        border-left: 4px solid #F59E0B;
        background: linear-gradient(135deg, #FFFBEB 0%, #FFFFFF 100%);
    }
    
    .prospect-card {
        background: linear-gradient(135deg, #DBEAFE 0%, #BFDBFE 100%);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #3B82F6;
    }
    
    .summary-section {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    
    .returns-table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
    }
    
    .returns-table th {
        background: #1E3A5F;
        color: white;
        padding: 12px;
        text-align: left;
        font-weight: 600;
    }
    
    .returns-table td {
        padding: 12px;
        border-bottom: 1px solid #E5E7EB;
    }
    
    .returns-table tr:nth-child(even) {
        background: #F9FAFB;
    }
    
    .returns-table tr.highlight {
        background: #DBEAFE;
        font-weight: 600;
    }
    
    .tag {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        margin: 2px;
    }
    
    .tag-pool { background: #DBEAFE; color: #1E40AF; }
    .tag-no-pool { background: #FEE2E2; color: #991B1B; }
    .tag-premium { background: #D1FAE5; color: #065F46; }
    .tag-warning { background: #FEF3C7; color: #92400E; }
    
    .distance-badge {
        background: #E5E7EB;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        color: #374151;
    }
    
    .airbnb-link {
        color: #FF5A5F;
        text-decoration: none;
        font-weight: 500;
    }
    
    .section-header {
        background: linear-gradient(135deg, #1E3A5F 0%, #2D5A87 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 12px 12px 0 0;
        margin-top: 1.5rem;
        margin-bottom: 0;
    }
    
    .section-content {
        background: white;
        padding: 1.5rem;
        border-radius: 0 0 12px 12px;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    
    .talking-point {
        background: #F0FDF4;
        border-left: 4px solid #10B981;
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
    }
    
    .flag-item {
        background: #FFFBEB;
        border-left: 4px solid #F59E0B;
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# GEOCODING FUNCTIONS
# =============================================================================

def geocode_address(address: str) -> dict:
    """Geocode an address using OpenStreetMap Nominatim."""
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": address,
                "format": "json",
                "limit": 1,
                "countrycodes": "au"
            },
            headers={"User-Agent": "HoneyHomesAppraisalTool/1.0"}
        )
        
        if response.status_code == 200 and response.json():
            result = response.json()[0]
            return {
                "lat": float(result["lat"]),
                "lon": float(result["lon"]),
                "display_name": result.get("display_name", address)
            }
    except Exception as e:
        st.warning(f"Could not geocode address: {address}")
    
    return None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers using Haversine formula."""
    R = 6371  # Earth's radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


# =============================================================================
# PROPERTY RESEARCH FUNCTIONS
# =============================================================================

def search_property_online(address: str, api_key: str) -> dict:
    """Search for property details online using Claude."""
    if not api_key:
        return None
    
    prompt = f"""Search for information about this property: {address}

Look for:
1. Does it have a pool? (Yes/No/Unknown)
2. Number of bedrooms and bathrooms
3. Land size if available
4. Any notable features (renovated, views, outdoor areas, etc.)
5. Recent sale price if available
6. Distance to CBD/town centre

Return a JSON object with these fields:
{{
    "has_pool": "yes/no/unknown",
    "bedrooms": number or null,
    "bathrooms": number or null,
    "land_size": "string or null",
    "features": ["list", "of", "features"],
    "sale_price": "string or null",
    "distance_to_cbd": "string or null",
    "source": "where you found this info"
}}

If you cannot find specific information, use "unknown" or null. Be honest about what you can and cannot verify."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        if response.status_code == 200:
            text = response.json()["content"][0]["text"]
            # Try to extract JSON from the response
            try:
                # Find JSON in the response
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    return json.loads(text[start:end])
            except:
                pass
    except Exception as e:
        pass
    
    return None


def get_airbnb_listing_info(airbnb_id: str, api_key: str) -> dict:
    """Get information about an Airbnb listing using Claude to analyze it."""
    if not api_key or not airbnb_id:
        return None
    
    airbnb_url = f"https://www.airbnb.com.au/rooms/{airbnb_id}"
    
    prompt = f"""Analyze this Airbnb listing: {airbnb_url}

Look at the listing and provide:
1. Overall quality rating (1-10)
2. Does it have a pool? (Yes/No)
3. Key amenities visible
4. Photo quality assessment (poor/average/good/excellent)
5. Number of reviews and average rating if visible
6. Any standout features or concerns
7. How it's positioned (budget/mid-range/premium/luxury)

Return a JSON object:
{{
    "quality_score": 1-10,
    "has_pool": true/false,
    "key_amenities": ["list"],
    "photo_quality": "poor/average/good/excellent",
    "review_count": number or null,
    "avg_rating": number or null,
    "positioning": "budget/mid-range/premium/luxury",
    "standout_features": ["list"],
    "concerns": ["list"]
}}"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        if response.status_code == 200:
            text = response.json()["content"][0]["text"]
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    result = json.loads(text[start:end])
                    result["airbnb_url"] = airbnb_url
                    return result
            except:
                pass
    except Exception as e:
        pass
    
    return {"airbnb_url": airbnb_url}


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    """Create database connection."""
    try:
        conn = pymssql.connect(
            server=DB_CONFIG["server"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            port=DB_CONFIG["port"]
        )
        return conn
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None


def get_regional_comps(region: str, bedrooms: int) -> list:
    """Get comparable properties from the same region with similar bedroom count."""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor(as_dict=True)
    
    query = """
    SELECT 
        l.Nickname,
        l.Bedrooms,
        l.Bathrooms,
        l.Amenities,
        l.StreetAddress,
        l.FullAddress,
        l.AirbnbId,
        l.Latitude,
        l.Longitude,
        CONCAT(g.FirstName, ' ', g.LastName) as OwnerName,
        COUNT(DISTINCT CONCAT(bp.year, '-', bp.month)) as months_of_data,
        SUM(bp.total) as total_owner_payout,
        SUM(bp.accom) as total_gross_revenue,
        AVG(bp.total) as avg_monthly_payout,
        AVG(bp.accom) as avg_monthly_gross,
        AVG(bp.nights) as avg_nights
    FROM Listings l
    INNER JOIN BtListingPerformance bp ON l.Nickname = bp.listingName
    LEFT JOIN GuestyOwners g ON l.Owners = g.GuestyId
    WHERE l.Town = %s
    AND l.Bedrooms BETWEEN %s AND %s
    GROUP BY 
        l.Nickname, l.Bedrooms, l.Bathrooms, l.Amenities, 
        l.StreetAddress, l.FullAddress, l.AirbnbId, l.Latitude, l.Longitude,
        g.FirstName, g.LastName
    HAVING COUNT(DISTINCT CONCAT(bp.year, '-', bp.month)) >= 3
    ORDER BY SUM(bp.total) DESC
    """
    
    bed_min = max(1, bedrooms - 1)
    bed_max = bedrooms + 1
    
    try:
        cursor.execute(query, (region, bed_min, bed_max))
        results = cursor.fetchall()
        return results
    except Exception as e:
        st.error(f"Query failed: {e}")
        return []
    finally:
        conn.close()


def get_region_averages(region: str) -> dict:
    """Get average performance metrics for a region."""
    conn = get_db_connection()
    if not conn:
        return {}
    
    cursor = conn.cursor(as_dict=True)
    
    query = """
    SELECT 
        l.Bedrooms,
        COUNT(DISTINCT l.Nickname) as property_count,
        AVG(bp.total) as avg_monthly_payout,
        AVG(bp.accom) as avg_monthly_gross,
        AVG(bp.nights) as avg_nights
    FROM Listings l
    INNER JOIN BtListingPerformance bp ON l.Nickname = bp.listingName
    WHERE l.Town = %s
    GROUP BY l.Bedrooms
    ORDER BY l.Bedrooms
    """
    
    try:
        cursor.execute(query, (region,))
        results = cursor.fetchall()
        return {r['Bedrooms']: r for r in results}
    except Exception as e:
        st.error(f"Query failed: {e}")
        return {}
    finally:
        conn.close()


# =============================================================================
# LTR ESTIMATE
# =============================================================================

def get_ltr_estimate(region: str, bedrooms: int) -> dict:
    """Get long-term rental estimate for comparison."""
    weekly = LTR_ESTIMATES.get(region, {}).get(bedrooms, 450)
    annual = weekly * 52
    return {"weekly": weekly, "annual": annual}


# =============================================================================
# MAP GENERATION
# =============================================================================

def generate_map_html(prospect_coords: dict, comps_with_coords: list, prospect_address: str) -> str:
    """Generate HTML for an interactive map using Leaflet."""
    
    if not prospect_coords:
        return "<p>Could not generate map - address not found</p>"
    
    center_lat = prospect_coords["lat"]
    center_lon = prospect_coords["lon"]
    
    # Build markers JavaScript
    markers_js = f"""
        // Prospect marker (blue)
        L.marker([{prospect_coords['lat']}, {prospect_coords['lon']}], {{
            icon: L.divIcon({{
                className: 'prospect-marker',
                html: '<div style="background:#3B82F6;color:white;padding:8px 12px;border-radius:8px;font-weight:bold;box-shadow:0 2px 8px rgba(0,0,0,0.3);">📍 PROSPECT</div>',
                iconSize: [100, 40],
                iconAnchor: [50, 40]
            }})
        }}).addTo(map).bindPopup('<b>Prospect Property</b><br>{prospect_address}');
    """
    
    for i, comp in enumerate(comps_with_coords):
        if comp.get('coords'):
            annual_payout = (comp['avg_monthly_payout'] or 0) * 12
            distance = comp.get('distance', 0)
            has_pool = "🏊 Pool" if comp['Amenities'] and 'pool' in comp['Amenities'].lower() else ""
            
            markers_js += f"""
        L.marker([{comp['coords']['lat']}, {comp['coords']['lon']}], {{
            icon: L.divIcon({{
                className: 'comp-marker',
                html: '<div style="background:#10B981;color:white;padding:6px 10px;border-radius:6px;font-size:12px;box-shadow:0 2px 6px rgba(0,0,0,0.2);">{i+1}</div>',
                iconSize: [30, 30],
                iconAnchor: [15, 30]
            }})
        }}).addTo(map).bindPopup('<b>{comp["Nickname"]}</b><br>${annual_payout:,.0f}/year<br>{distance:.1f}km away<br>{has_pool}');
    """
    
    map_html = f"""
    <div id="map" style="height: 400px; border-radius: 12px; margin: 1rem 0;"></div>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        var map = L.map('map').setView([{center_lat}, {center_lon}], 13);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);
        
        {markers_js}
    </script>
    """
    
    return map_html


# =============================================================================
# CLAUDE APPRAISAL GENERATION
# =============================================================================

def generate_appraisal(property_details: dict, comps: list, ltr_estimate: dict, 
                       prospect_research: dict, comp_research: list) -> str:
    """Use Claude to generate the appraisal summary."""
    
    if not ANTHROPIC_API_KEY:
        return "⚠️ API key not configured."
    
    # Build detailed comps text
    comps_text = ""
    payout_values = []
    
    for i, comp in enumerate(comps[:5], 1):
        annual_payout = (comp['avg_monthly_payout'] or 0) * 12
        annual_gross = (comp['avg_monthly_gross'] or 0) * 12
        avg_nights = comp['avg_nights'] or 0
        payout_values.append(annual_payout)
        
        has_pool = "Yes" if comp['Amenities'] and 'pool' in comp['Amenities'].lower() else "No"
        distance = comp.get('distance', 'Unknown')
        
        # Add Airbnb research if available
        airbnb_info = ""
        if i <= len(comp_research) and comp_research[i-1]:
            cr = comp_research[i-1]
            airbnb_info = f"""
    - Airbnb Quality Score: {cr.get('quality_score', 'N/A')}/10
    - Photo Quality: {cr.get('photo_quality', 'N/A')}
    - Positioning: {cr.get('positioning', 'N/A')}
    - Reviews: {cr.get('review_count', 'N/A')} ({cr.get('avg_rating', 'N/A')} avg)"""
        
        comps_text += f"""
Comp {i}: {comp['Nickname']}
- Distance from prospect: {distance:.1f}km
- Bedrooms/Bathrooms: {comp['Bedrooms']}/{comp['Bathrooms']}
- Pool: {has_pool}
- Annual Owner Payout: ${annual_payout:,.0f}
- Annual Gross Revenue: ${annual_gross:,.0f}
- Avg nights booked/month: {avg_nights:.0f}
- Airbnb URL: https://www.airbnb.com.au/rooms/{comp['AirbnbId']}{airbnb_info}
"""
    
    # Prospect property research summary
    prospect_info = ""
    if prospect_research:
        prospect_info = f"""
PROSPECT PROPERTY RESEARCH:
- Has Pool: {prospect_research.get('has_pool', 'Unknown')}
- Features Found: {', '.join(prospect_research.get('features', [])) or 'None found'}
- Sale Price: {prospect_research.get('sale_price', 'Unknown')}
- Distance to CBD: {prospect_research.get('distance_to_cbd', 'Unknown')}
"""
    
    # Calculate stats
    min_payout = min(payout_values) if payout_values else 0
    max_payout = max(payout_values) if payout_values else 0
    avg_payout = sum(payout_values) / len(payout_values) if payout_values else 0
    
    # Count pools in comps
    pool_count = sum(1 for c in comps[:5] if c['Amenities'] and 'pool' in c['Amenities'].lower())
    prospect_has_pool = prospect_research and prospect_research.get('has_pool', '').lower() == 'yes'
    
    prompt = f"""You are an STR Appraisal Agent. Generate a professional, data-driven appraisal.

PROSPECT PROPERTY:
- Address: {property_details['address']}
- Region: {property_details['region']}
- Bedrooms: {property_details['bedrooms']}
- Bathrooms: {property_details['bathrooms']}
- Features (user provided): {property_details.get('features', 'Not specified')}
- Estimated Value: {property_details.get('value', 'Not specified')}
{prospect_info}

COMPARABLE PROPERTIES (sorted by distance):
{comps_text}

KEY STATISTICS:
- Pool count in comps: {pool_count} out of {len(comps[:5])} have pools
- Prospect has pool: {'Yes' if prospect_has_pool else 'No/Unknown'}
- Comp payout range: ${min_payout:,.0f} - ${max_payout:,.0f}
- Comp average payout: ${avg_payout:,.0f}

LTR COMPARISON:
- Weekly LTR estimate: ${ltr_estimate['weekly']}/week
- Annual LTR estimate: ${ltr_estimate['annual']:,}/year

INSTRUCTIONS:
1. Be CONSERVATIVE - new properties take 3-6 months to ramp up
2. Heavily weight the pool factor - properties with pools significantly outperform
3. Consider distance - closer comps are more relevant
4. Factor in quality differences from Airbnb research
5. Always compare to LTR returns

Generate the appraisal with these sections (keep each section concise):

**PROPERTY SUMMARY** (2-3 sentences)

**MARKET POSITION** 
How does this property compare to comps on: location, amenities, quality potential?

**PROJECTED ANNUAL RETURNS**
Show Conservative/Mid-range/Optimistic scenarios with specific reasoning.
Always show the STR premium over LTR.

**KEY FACTORS**
- Advantages this property has
- Disadvantages/gaps vs top performers
- Critical questions for the owner

**SALES TALKING POINTS**
3-4 bullet points ready for the sales conversation. Lead with the STR vs LTR comparison.

Be specific with numbers. Keep total response under 600 words."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        else:
            return f"⚠️ API Error: {response.status_code}"
    except Exception as e:
        return f"⚠️ Error: {e}"


# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

def display_comp_card(comp: dict, index: int, is_top: bool = False):
    """Display a single comp property card."""
    annual_payout = (comp['avg_monthly_payout'] or 0) * 12
    annual_gross = (comp['avg_monthly_gross'] or 0) * 12
    has_pool = comp['Amenities'] and 'pool' in comp['Amenities'].lower()
    distance = comp.get('distance', 0)
    
    card_class = "comp-card top-performer" if is_top else "comp-card"
    pool_tag = '<span class="tag tag-pool">🏊 Pool</span>' if has_pool else '<span class="tag tag-no-pool">No Pool</span>'
    top_badge = '<span class="tag tag-premium">⭐ Top Performer</span>' if is_top else ''
    
    airbnb_link = ""
    if comp.get('AirbnbId'):
        airbnb_link = f'<a href="https://www.airbnb.com.au/rooms/{comp["AirbnbId"]}" target="_blank" class="airbnb-link">View on Airbnb →</a>'
    
    st.markdown(f"""
    <div class="{card_class}">
        <div style="display:flex;justify-content:space-between;align-items:start;">
            <div>
                <strong style="font-size:1.1rem;">{index}. {comp['Nickname']}</strong>
                {top_badge}
                <br>
                <span style="color:#6B7280;">{comp['Bedrooms']} bed · {comp['Bathrooms']} bath</span>
                <span class="distance-badge" style="margin-left:10px;">📍 {distance:.1f}km away</span>
            </div>
            <div style="text-align:right;">
                <strong style="font-size:1.25rem;color:#059669;">${annual_payout:,.0f}</strong>
                <br>
                <span style="color:#6B7280;font-size:0.9rem;">annual payout</span>
            </div>
        </div>
        <div style="margin-top:10px;">
            {pool_tag}
            <span style="color:#6B7280;margin-left:15px;">{comp['months_of_data']} months data · {comp['avg_nights'] or 0:.0f} nights/month</span>
        </div>
        <div style="margin-top:8px;">
            {airbnb_link}
        </div>
    </div>
    """, unsafe_allow_html=True)


def display_returns_table(comps: list, ltr_estimate: dict, prospect_has_pool: bool):
    """Display the projected returns comparison table."""
    payout_values = [(c['avg_monthly_payout'] or 0) * 12 for c in comps[:5]]
    
    if not payout_values:
        return
    
    min_payout = min(payout_values)
    max_payout = max(payout_values)
    avg_payout = sum(payout_values) / len(payout_values)
    
    # Adjust for no pool if applicable
    pool_count = sum(1 for c in comps[:5] if c['Amenities'] and 'pool' in c['Amenities'].lower())
    pool_adjustment = 0.85 if (pool_count >= 2 and not prospect_has_pool) else 1.0
    
    conservative = min_payout * 0.9 * pool_adjustment  # 10% below lowest + pool adjustment
    midrange = avg_payout * pool_adjustment
    optimistic = max_payout * pool_adjustment
    
    str_premium = midrange - ltr_estimate['annual']
    str_premium_pct = (str_premium / ltr_estimate['annual'] * 100) if ltr_estimate['annual'] > 0 else 0
    
    weekly_conservative = conservative / 52
    weekly_midrange = midrange / 52
    weekly_optimistic = optimistic / 52
    
    st.markdown(f"""
    <table class="returns-table">
        <tr>
            <th>Management Type</th>
            <th>Weekly</th>
            <th>Annual</th>
            <th>Notes</th>
        </tr>
        <tr>
            <td><strong>Short-Term Rental</strong></td>
            <td>${weekly_conservative:,.0f} - ${weekly_optimistic:,.0f}</td>
            <td>${conservative:,.0f} - ${optimistic:,.0f}</td>
            <td>Based on {len(payout_values)} comps</td>
        </tr>
        <tr>
            <td>Long-Term Rental</td>
            <td>${ltr_estimate['weekly']}</td>
            <td>${ltr_estimate['annual']:,}</td>
            <td>Current market rate</td>
        </tr>
        <tr class="highlight">
            <td><strong>STR Premium</strong></td>
            <td>+${(weekly_midrange - ltr_estimate['weekly']):,.0f}</td>
            <td>+${str_premium:,.0f}</td>
            <td><strong>{str_premium_pct:.0f}% above LTR</strong></td>
        </tr>
    </table>
    
    <div style="margin-top:1rem;">
        <strong>Scenario Breakdown:</strong>
        <ul style="margin-top:0.5rem;">
            <li><strong>Conservative (${conservative:,.0f}):</strong> New property ramp-up, below lowest comp{', no pool adjustment' if pool_adjustment < 1 else ''}</li>
            <li><strong>Mid-range (${midrange:,.0f}):</strong> Average of comparable properties</li>
            <li><strong>Optimistic (${optimistic:,.0f}):</strong> Achievable if matching top performer quality</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# MAIN APP
# =============================================================================

def main():
    st.markdown("# 🏠 Appraisal Tool")
    st.markdown("*Generate data-driven STR appraisals with market analysis*")
    st.markdown("---")
    
    # Input Section
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### Property Details")
        
        address = st.text_input(
            "Property Address",
            placeholder="e.g., 39 Stonehaven Ave, Dubbo NSW 2830"
        )
        
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            region = st.selectbox("Region", REGIONS)
        with col_b:
            bedrooms = st.number_input("Bedrooms", min_value=1, max_value=10, value=4)
        with col_c:
            bathrooms = st.number_input("Bathrooms", min_value=1, max_value=10, value=2)
        
        features = st.text_area(
            "Known Features (optional)",
            placeholder="Add any features you already know about: pool, renovation, views, etc.",
            height=80
        )
        
        value = st.text_input(
            "Property Value (optional)",
            placeholder="e.g., $750,000"
        )
    
    with col2:
        st.markdown("### Quick Stats")
        ltr = get_ltr_estimate(region, bedrooms)
        averages = get_region_averages(region)
        
        if bedrooms in averages:
            avg = averages[bedrooms]
            annual_payout = (avg['avg_monthly_payout'] or 0) * 12
            str_premium = annual_payout - ltr['annual']
            
            st.markdown(f"""
            <div class="metric-card">
                <strong>{bedrooms}-bed in {region}</strong><br><br>
                📊 <strong>{avg['property_count']}</strong> properties in portfolio<br>
                💰 <strong>${annual_payout:,.0f}</strong>/year avg STR payout<br>
                🏠 <strong>${ltr['annual']:,}</strong>/year LTR estimate<br>
                📈 <strong>+${str_premium:,.0f}</strong> STR premium
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Generate Button
    if st.button("🔍 Generate Appraisal", use_container_width=True):
        if not address:
            st.warning("Please enter a property address.")
            return
        
        # Progress tracking
        progress = st.progress(0)
        status = st.empty()
        
        # Step 1: Geocode prospect
        status.text("📍 Finding property location...")
        progress.progress(10)
        prospect_coords = geocode_address(address)
        
        # Step 2: Research prospect property online
        status.text("🔎 Researching property online...")
        progress.progress(20)
        prospect_research = search_property_online(address, ANTHROPIC_API_KEY)
        
        # Step 3: Get comps from database
        status.text("📊 Finding comparable properties...")
        progress.progress(30)
        comps = get_regional_comps(region, bedrooms)
        
        if not comps:
            st.warning(f"No comparable properties found in {region}.")
            return
        
        # Step 4: Geocode comps and calculate distances
        status.text("📍 Calculating distances...")
        progress.progress(40)
        
        for comp in comps:
            # Use stored coordinates if available, otherwise geocode
            if comp.get('Latitude') and comp.get('Longitude'):
                comp['coords'] = {'lat': float(comp['Latitude']), 'lon': float(comp['Longitude'])}
            elif comp.get('FullAddress'):
                comp['coords'] = geocode_address(comp['FullAddress'])
            else:
                comp['coords'] = None
            
            # Calculate distance
            if prospect_coords and comp.get('coords'):
                comp['distance'] = calculate_distance(
                    prospect_coords['lat'], prospect_coords['lon'],
                    comp['coords']['lat'], comp['coords']['lon']
                )
            else:
                comp['distance'] = 999
        
        # Sort by distance
        comps.sort(key=lambda x: x.get('distance', 999))
        
        # Step 5: Research Airbnb listings for top comps
        status.text("🏠 Analyzing Airbnb listings...")
        progress.progress(60)
        
        comp_research = []
        for comp in comps[:4]:  # Top 4 closest comps
            if comp.get('AirbnbId'):
                info = get_airbnb_listing_info(comp['AirbnbId'], ANTHROPIC_API_KEY)
                comp_research.append(info)
            else:
                comp_research.append(None)
        
        # Step 6: Get LTR estimate
        ltr_estimate = get_ltr_estimate(region, bedrooms)
        
        # Step 7: Generate appraisal
        status.text("✍️ Generating appraisal...")
        progress.progress(80)
        
        property_details = {
            "address": address,
            "region": region,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "features": features,
            "value": value
        }
        
        appraisal_text = generate_appraisal(
            property_details, comps, ltr_estimate,
            prospect_research, comp_research
        )
        
        progress.progress(100)
        status.empty()
        progress.empty()
        
        # =================================================================
        # DISPLAY RESULTS
        # =================================================================
        
        # Prospect Property Card
        prospect_has_pool = prospect_research and prospect_research.get('has_pool', '').lower() == 'yes'
        pool_tag = '<span class="tag tag-pool">🏊 Pool</span>' if prospect_has_pool else '<span class="tag tag-no-pool">No Pool Detected</span>'
        
        features_found = ""
        if prospect_research and prospect_research.get('features'):
            features_found = " · ".join(prospect_research.get('features', []))
        
        st.markdown(f"""
        <div class="prospect-card">
            <strong style="font-size:1.2rem;">📍 Prospect Property</strong><br>
            <span style="font-size:1.1rem;">{address}</span><br>
            <span>{bedrooms} bed · {bathrooms} bath</span> {pool_tag}<br>
            {f'<span style="color:#6B7280;font-size:0.9rem;">Features found: {features_found}</span>' if features_found else ''}
        </div>
        """, unsafe_allow_html=True)
        
        # Map
        st.markdown('<div class="section-header">🗺️ Location & Comparables</div>', unsafe_allow_html=True)
        map_html = generate_map_html(prospect_coords, comps[:5], address)
        st.components.v1.html(map_html, height=450)
        
        # Comparable Properties
        st.markdown('<div class="section-header">📊 Comparable Properties (by distance)</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-content">', unsafe_allow_html=True)
        
        for i, comp in enumerate(comps[:5], 1):
            is_top = i == 1 or (comp['avg_monthly_payout'] or 0) * 12 == max((c['avg_monthly_payout'] or 0) * 12 for c in comps[:5])
            display_comp_card(comp, i, is_top)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Returns Comparison
        st.markdown('<div class="section-header">💰 Projected Returns</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-content">', unsafe_allow_html=True)
        display_returns_table(comps, ltr_estimate, prospect_has_pool)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # AI Appraisal Summary
        st.markdown('<div class="section-header">📝 Appraisal Summary</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-content">', unsafe_allow_html=True)
        st.markdown(appraisal_text)
        st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
