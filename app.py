"""
Appraisal Tool v3.2
- Fixed formatting in Claude responses
- Added Streamlit native map
- LTR estimate lookup
"""

import streamlit as st
import pymssql
import requests
import os
import math
import pandas as pd
from datetime import datetime
from decimal import Decimal

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

# Regional center coordinates
REGION_COORDS = {
    "Wagga Wagga": {"lat": -35.1082, "lon": 147.3598},
    "Orange": {"lat": -33.2836, "lon": 149.1013},
    "Bathurst": {"lat": -33.4196, "lon": 149.5777},
    "Dubbo": {"lat": -32.2569, "lon": 148.6011},
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def to_float(val):
    """Convert Decimal or any numeric to float."""
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)

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
</style>
""", unsafe_allow_html=True)

# =============================================================================
# GEOCODING
# =============================================================================

def geocode_address(address: str, region: str = None) -> dict:
    """Geocode an address using OpenStreetMap Nominatim."""
    if not address:
        return None
    
    # Add NSW Australia if not present
    if "NSW" not in address.upper():
        address = f"{address}, NSW, Australia"
    elif "Australia" not in address:
        address = f"{address}, Australia"
    
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "au"},
            headers={"User-Agent": "AppraisalTool/1.0"},
            timeout=5
        )
        
        if response.status_code == 200 and response.json():
            result = response.json()[0]
            return {"lat": float(result["lat"]), "lon": float(result["lon"]), "found": True}
    except:
        pass
    
    # Fallback to region center
    if region and region in REGION_COORDS:
        return {"lat": REGION_COORDS[region]["lat"], "lon": REGION_COORDS[region]["lon"], "found": False}
    
    return None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km using Haversine formula."""
    R = 6371
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    try:
        return pymssql.connect(
            server=DB_CONFIG["server"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            port=DB_CONFIG["port"]
        )
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None


def get_regional_comps(region: str, bedrooms: int) -> list:
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor(as_dict=True)
    
    query = """
    SELECT 
        l.Nickname, l.Bedrooms, l.Bathrooms, l.Amenities,
        l.StreetAddress, l.FullAddress, l.AirbnbId, l.Latitude, l.Longitude,
        CONCAT(g.FirstName, ' ', g.LastName) as OwnerName,
        COUNT(DISTINCT CONCAT(bp.year, '-', bp.month)) as months_of_data,
        AVG(bp.total) as avg_monthly_payout,
        AVG(bp.accom) as avg_monthly_gross,
        AVG(bp.nights) as avg_nights
    FROM Listings l
    INNER JOIN BtListingPerformance bp ON l.Nickname = bp.listingName
    LEFT JOIN GuestyOwners g ON l.Owners = g.GuestyId
    WHERE l.Town = %s AND l.Bedrooms BETWEEN %s AND %s
    GROUP BY l.Nickname, l.Bedrooms, l.Bathrooms, l.Amenities, 
        l.StreetAddress, l.FullAddress, l.AirbnbId, l.Latitude, l.Longitude, g.FirstName, g.LastName
    HAVING COUNT(DISTINCT CONCAT(bp.year, '-', bp.month)) >= 3
    ORDER BY SUM(bp.total) DESC
    """
    
    try:
        cursor.execute(query, (region, max(1, bedrooms - 1), bedrooms + 1))
        results = cursor.fetchall()
        for r in results:
            r['avg_monthly_payout'] = to_float(r.get('avg_monthly_payout'))
            r['avg_monthly_gross'] = to_float(r.get('avg_monthly_gross'))
            r['avg_nights'] = to_float(r.get('avg_nights'))
            if r.get('Latitude'): r['Latitude'] = to_float(r['Latitude'])
            if r.get('Longitude'): r['Longitude'] = to_float(r['Longitude'])
        return results
    except Exception as e:
        st.error(f"Query failed: {e}")
        return []
    finally:
        conn.close()


def get_region_averages(region: str) -> dict:
    conn = get_db_connection()
    if not conn:
        return {}
    
    cursor = conn.cursor(as_dict=True)
    
    query = """
    SELECT l.Bedrooms, COUNT(DISTINCT l.Nickname) as property_count,
        AVG(bp.total) as avg_monthly_payout, AVG(bp.nights) as avg_nights
    FROM Listings l
    INNER JOIN BtListingPerformance bp ON l.Nickname = bp.listingName
    WHERE l.Town = %s
    GROUP BY l.Bedrooms
    """
    
    try:
        cursor.execute(query, (region,))
        results = cursor.fetchall()
        return {r['Bedrooms']: {
            'property_count': r['property_count'],
            'avg_monthly_payout': to_float(r['avg_monthly_payout']),
            'avg_nights': to_float(r['avg_nights'])
        } for r in results}
    except:
        return {}
    finally:
        conn.close()


# =============================================================================
# LTR ESTIMATE - Search online
# =============================================================================

def get_ltr_estimate(region: str, bedrooms: int) -> dict:
    """Get LTR estimate - use Claude to search for current rental rates."""
    
    # Default estimates (will be overridden by search)
    defaults = {
        "Wagga Wagga": {2: 400, 3: 480, 4: 580, 5: 680},
        "Orange": {2: 380, 3: 460, 4: 550, 5: 650},
        "Bathurst": {2: 390, 3: 470, 4: 560, 5: 660},
        "Dubbo": {2: 370, 3: 450, 4: 540, 5: 640},
    }
    
    weekly = defaults.get(region, {}).get(bedrooms, 500)
    
    # Try to get better estimate via Claude
    if ANTHROPIC_API_KEY:
        try:
            prompt = f"""What is the current average weekly rental price for a {bedrooms}-bedroom house in {region}, NSW, Australia?

Search realestate.com.au or domain.com.au mentally and give me a realistic estimate.

Reply with ONLY a number (the weekly rent in dollars). No other text. Example: 550"""

            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=10
            )
            
            if response.status_code == 200:
                text = response.json()["content"][0]["text"].strip()
                # Extract number
                import re
                numbers = re.findall(r'\d+', text)
                if numbers:
                    weekly = int(numbers[0])
        except:
            pass
    
    return {"weekly": weekly, "annual": weekly * 52}


# =============================================================================
# CLAUDE APPRAISAL
# =============================================================================

def generate_appraisal(property_details: dict, comps: list, ltr_estimate: dict) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ API key not configured."
    
    # Build comps summary
    comps_text = ""
    payout_values = []
    
    for i, comp in enumerate(comps[:5], 1):
        annual_payout = comp['avg_monthly_payout'] * 12
        payout_values.append(annual_payout)
        has_pool = "Yes" if comp.get('Amenities') and 'pool' in comp['Amenities'].lower() else "No"
        distance = comp.get('distance', 0)
        
        comps_text += f"""
{i}. {comp['Nickname']}
   - {comp['Bedrooms']}bed/{comp['Bathrooms']}bath, Pool: {has_pool}
   - Distance: {distance:.1f}km
   - Annual payout: ${annual_payout:,.0f}
   - Nights/month: {comp['avg_nights']:.0f}
"""
    
    min_pay = min(payout_values) if payout_values else 0
    max_pay = max(payout_values) if payout_values else 0
    avg_pay = sum(payout_values) / len(payout_values) if payout_values else 0
    pool_count = sum(1 for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower())
    
    prompt = f"""Write a brief STR appraisal for this property. 

IMPORTANT FORMATTING RULES:
- Always put spaces around dollar amounts: "$38,000 annually" NOT "$38kannually"
- Write numbers clearly: "$54,000" NOT "$54k"
- Separate comparisons with spaces: "$48,000 vs $25,000" NOT "$48kvs$25k"

PROPERTY:
Address: {property_details['address']}
Config: {property_details['bedrooms']} bed / {property_details['bathrooms']} bath
Region: {property_details['region']}
Features: {property_details.get('features', 'Not specified')}

COMPARABLES (sorted by distance):
{comps_text}

STATS:
- Comp range: ${min_pay:,.0f} to ${max_pay:,.0f} annual payout
- Comp average: ${avg_pay:,.0f}
- Pools: {pool_count} of 5 comps have pools

LTR COMPARISON:
- Weekly LTR rent: ${ltr_estimate['weekly']} per week
- Annual LTR: ${ltr_estimate['annual']:,} per year

Write these sections (keep brief):

## Summary
2 sentences about the property's position in the market.

## Projected Returns
Show three scenarios with CLEAR formatting:
- **Conservative**: $XX,XXX annually (explain why)
- **Mid-range**: $XX,XXX annually (explain why)  
- **Optimistic**: $XX,XXX annually (explain why)

STR Premium over LTR: $XX,XXX annually (XX% above LTR of ${ltr_estimate['annual']:,})

## Key Factors
**Advantages:**
- Point 1
- Point 2

**Disadvantages:**
- Point 1
- Point 2

## Sales Points
3 bullet points for the owner conversation. Use clear dollar amounts with proper spacing.

Keep total under 350 words."""

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
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        return f"⚠️ API Error: {response.status_code}"
    except Exception as e:
        return f"⚠️ Error: {e}"


# =============================================================================
# MAIN APP
# =============================================================================

def main():
    st.markdown("# 🏠 Appraisal Tool")
    st.markdown("*Generate data-driven STR appraisals*")
    st.markdown("---")
    
    # Input Section
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### Property Details")
        address = st.text_input("Property Address", placeholder="e.g., 39 Stonehaven Ave, Dubbo NSW 2830")
        
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            region = st.selectbox("Region", REGIONS)
        with col_b:
            bedrooms = st.number_input("Bedrooms", min_value=1, max_value=10, value=4)
        with col_c:
            bathrooms = st.number_input("Bathrooms", min_value=1, max_value=10, value=2)
        
        features = st.text_area("Known Features (optional)", placeholder="Pool, renovation, etc.", height=80)
        value = st.text_input("Property Value (optional)", placeholder="e.g., $750,000")
    
    with col2:
        st.markdown("### Quick Stats")
        averages = get_region_averages(region)
        
        if bedrooms in averages:
            avg = averages[bedrooms]
            annual_payout = avg['avg_monthly_payout'] * 12
            
            # Get LTR estimate
            ltr = get_ltr_estimate(region, bedrooms)
            str_premium = annual_payout - ltr['annual']
            
            st.markdown(f"""
            <div class="metric-card">
                <strong>{bedrooms}-bed in {region}</strong><br><br>
                📊 <strong>{avg['property_count']}</strong> properties<br>
                💰 <strong>${annual_payout:,.0f}</strong>/year STR<br>
                🏠 <strong>${ltr['weekly']}/week</strong> LTR (${ltr['annual']:,}/yr)<br>
                📈 <strong>+${str_premium:,.0f}</strong> STR premium
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    if st.button("🔍 Generate Appraisal", use_container_width=True):
        if not address:
            st.warning("Please enter a property address.")
            return
        
        # Get comps
        with st.spinner("Finding comparable properties..."):
            comps = get_regional_comps(region, bedrooms)
        
        if not comps:
            st.warning(f"No comparable properties found in {region}.")
            return
        
        # Geocode and calculate distances
        with st.spinner("Calculating distances..."):
            prospect_coords = geocode_address(address, region)
            
            for comp in comps:
                comp_lat = comp.get('Latitude')
                comp_lon = comp.get('Longitude')
                
                if prospect_coords and comp_lat and comp_lon:
                    comp['distance'] = calculate_distance(
                        prospect_coords['lat'], prospect_coords['lon'],
                        comp_lat, comp_lon
                    )
                    comp['has_coords'] = True
                else:
                    comp['distance'] = 0
                    comp['has_coords'] = False
            
            # Sort by distance
            comps.sort(key=lambda x: x.get('distance', 0) if x.get('distance', 0) > 0 else 999)
        
        # Get LTR estimate
        with st.spinner("Looking up rental rates..."):
            ltr_estimate = get_ltr_estimate(region, bedrooms)
        
        # =================================================================
        # DISPLAY RESULTS
        # =================================================================
        
        # Prospect
        st.markdown("### 📍 Prospect Property")
        st.info(f"**{address}** — {bedrooms} bed, {bathrooms} bath")
        
        # Map
        st.markdown("### 🗺️ Location Map")
        
        map_data = []
        if prospect_coords:
            map_data.append({
                'lat': prospect_coords['lat'],
                'lon': prospect_coords['lon'],
                'name': 'PROSPECT'
            })
        
        for comp in comps[:5]:
            if comp.get('Latitude') and comp.get('Longitude'):
                map_data.append({
                    'lat': comp['Latitude'],
                    'lon': comp['Longitude'],
                    'name': comp['Nickname']
                })
        
        if map_data:
            df = pd.DataFrame(map_data)
            st.map(df, latitude='lat', longitude='lon', size=100)
            st.caption("📍 Blue = Prospect | Other markers = Comparable properties")
        else:
            st.warning("Could not generate map - coordinates not available")
        
        # Comparables
        st.markdown("### 📊 Comparable Properties")
        
        for i, comp in enumerate(comps[:5], 1):
            annual_payout = comp['avg_monthly_payout'] * 12
            has_pool = comp.get('Amenities') and 'pool' in comp['Amenities'].lower()
            distance = comp.get('distance', 0)
            
            dist_text = f"{distance:.1f}km" if distance > 0 else "Unknown"
            pool_text = "🏊 Pool" if has_pool else "❌ No pool"
            pool_color = "green" if has_pool else "red"
            
            is_top = annual_payout == max(c['avg_monthly_payout'] * 12 for c in comps[:5])
            top_badge = " ⭐" if is_top else ""
            
            airbnb_id = comp.get('AirbnbId')
            airbnb_link = f"[Airbnb](https://www.airbnb.com.au/rooms/{airbnb_id})" if airbnb_id else ""
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{i}. {comp['Nickname']}{top_badge}**")
                st.caption(f"{comp['Bedrooms']}bed · {comp['Bathrooms']}bath · 📍 {dist_text} · :{pool_color}[{pool_text}] · {airbnb_link}")
            with col2:
                st.metric("Annual", f"${annual_payout:,.0f}")
            
            st.divider()
        
        # Projected Returns
        st.markdown("### 💰 Projected Returns")
        
        payout_values = [c['avg_monthly_payout'] * 12 for c in comps[:5]]
        min_payout = min(payout_values)
        max_payout = max(payout_values)
        avg_payout = sum(payout_values) / len(payout_values)
        
        # Pool adjustment
        prospect_has_pool = features and 'pool' in features.lower()
        pool_count = sum(1 for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower())
        adjustment = 0.85 if (pool_count >= 2 and not prospect_has_pool) else 1.0
        
        conservative = min_payout * 0.9 * adjustment
        midrange = avg_payout * adjustment
        optimistic = max_payout * adjustment
        
        str_premium = midrange - ltr_estimate['annual']
        str_premium_pct = (str_premium / ltr_estimate['annual'] * 100) if ltr_estimate['annual'] > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Conservative", f"${conservative:,.0f}")
        with col2:
            st.metric("Mid-range", f"${midrange:,.0f}")
        with col3:
            st.metric("Optimistic", f"${optimistic:,.0f}")
        
        # LTR Comparison
        st.markdown("#### Long-Term Rental Comparison")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("LTR Weekly", f"${ltr_estimate['weekly']}")
        with col2:
            st.metric("LTR Annual", f"${ltr_estimate['annual']:,}")
        with col3:
            st.metric("STR Premium", f"+${str_premium:,.0f}", f"{str_premium_pct:.0f}% above LTR")
        
        if adjustment < 1:
            st.warning(f"⚠️ Estimates reduced by 15% — {pool_count} of 5 comps have pools but prospect does not")
        
        # AI Summary
        st.markdown("### 📝 Appraisal Summary")
        
        with st.spinner("Generating appraisal..."):
            property_details = {
                "address": address,
                "region": region,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "features": features,
                "value": value
            }
            appraisal_text = generate_appraisal(property_details, comps, ltr_estimate)
        
        st.markdown(appraisal_text)


if __name__ == "__main__":
    main()
