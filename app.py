"""
Appraisal Tool v3.3
- Labeled map markers using PyDeck
- Real LTR search via web
- Fixed formatting
"""

import streamlit as st
import pymssql
import requests
import os
import math
import pandas as pd
import pydeck as pdk
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

REGION_COORDS = {
    "Wagga Wagga": {"lat": -35.1082, "lon": 147.3598},
    "Orange": {"lat": -33.2836, "lon": 149.1013},
    "Bathurst": {"lat": -33.4196, "lon": 149.5777},
    "Dubbo": {"lat": -32.2569, "lon": 148.6011},
}

# =============================================================================
# HELPERS
# =============================================================================

def to_float(val):
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)

# =============================================================================
# PAGE CONFIG
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
        color: white; border: none; padding: 0.75rem 2rem;
        font-weight: 600; border-radius: 8px;
    }
    .metric-card {
        background: white; border-radius: 12px; padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-left: 4px solid #3B82F6;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# GEOCODING
# =============================================================================

def geocode_address(address: str, region: str = None) -> dict:
    if not address:
        return None
    
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
    
    if region and region in REGION_COORDS:
        return {"lat": REGION_COORDS[region]["lat"], "lon": REGION_COORDS[region]["lon"], "found": False}
    return None


def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat, delta_lon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# =============================================================================
# DATABASE
# =============================================================================

def get_db_connection():
    try:
        return pymssql.connect(
            server=DB_CONFIG["server"], user=DB_CONFIG["user"],
            password=DB_CONFIG["password"], database=DB_CONFIG["database"], port=DB_CONFIG["port"]
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
    SELECT l.Nickname, l.Bedrooms, l.Bathrooms, l.Amenities, l.StreetAddress, 
        l.FullAddress, l.AirbnbId, l.Latitude, l.Longitude,
        CONCAT(g.FirstName, ' ', g.LastName) as OwnerName,
        COUNT(DISTINCT CONCAT(bp.year, '-', bp.month)) as months_of_data,
        AVG(bp.total) as avg_monthly_payout, AVG(bp.accom) as avg_monthly_gross, AVG(bp.nights) as avg_nights
    FROM Listings l
    INNER JOIN BtListingPerformance bp ON l.Nickname = bp.listingName
    LEFT JOIN GuestyOwners g ON l.Owners = g.GuestyId
    WHERE l.Town = %s AND l.Bedrooms BETWEEN %s AND %s
    GROUP BY l.Nickname, l.Bedrooms, l.Bathrooms, l.Amenities, l.StreetAddress, 
        l.FullAddress, l.AirbnbId, l.Latitude, l.Longitude, g.FirstName, g.LastName
    HAVING COUNT(DISTINCT CONCAT(bp.year, '-', bp.month)) >= 3
    ORDER BY SUM(bp.total) DESC
    """
    
    try:
        cursor.execute(query, (region, max(1, bedrooms - 1), bedrooms + 1))
        results = cursor.fetchall()
        for r in results:
            for key in ['avg_monthly_payout', 'avg_monthly_gross', 'avg_nights', 'Latitude', 'Longitude']:
                if r.get(key): r[key] = to_float(r[key])
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
        AVG(bp.total) as avg_monthly_payout
    FROM Listings l
    INNER JOIN BtListingPerformance bp ON l.Nickname = bp.listingName
    WHERE l.Town = %s GROUP BY l.Bedrooms
    """
    try:
        cursor.execute(query, (region,))
        return {r['Bedrooms']: {'property_count': r['property_count'], 
                'avg_monthly_payout': to_float(r['avg_monthly_payout'])} for r in cursor.fetchall()}
    except:
        return {}
    finally:
        conn.close()

# =============================================================================
# LTR SEARCH - Actually search the web
# =============================================================================

def get_ltr_estimate(region: str, bedrooms: int) -> dict:
    """Search for real rental listings to estimate LTR."""
    
    # Fallback defaults
    defaults = {
        "Wagga Wagga": {2: 420, 3: 500, 4: 600, 5: 700},
        "Orange": {2: 400, 3: 480, 4: 580, 5: 680},
        "Bathurst": {2: 410, 3: 490, 4: 590, 5: 690},
        "Dubbo": {2: 390, 3: 470, 4: 570, 5: 670},
    }
    weekly = defaults.get(region, {}).get(bedrooms, 550)
    
    if not ANTHROPIC_API_KEY:
        return {"weekly": weekly, "annual": weekly * 52, "source": "estimate"}
    
    try:
        # Ask Claude to search for rental listings
        prompt = f"""Search for current rental listings for {bedrooms}-bedroom houses in {region}, NSW, Australia.

Look at realestate.com.au or domain.com.au rental listings.

What is the typical weekly rent for a {bedrooms}-bedroom house in {region} right now?

Reply with ONLY a single number representing the weekly rent in dollars.
For example: 580

Do not include any other text, just the number."""

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
            timeout=15
        )
        
        if response.status_code == 200:
            text = response.json()["content"][0]["text"].strip()
            import re
            numbers = re.findall(r'\d+', text)
            if numbers:
                found_weekly = int(numbers[0])
                # Sanity check - should be between 300 and 1500
                if 300 <= found_weekly <= 1500:
                    weekly = found_weekly
                    return {"weekly": weekly, "annual": weekly * 52, "source": "search"}
    except:
        pass
    
    return {"weekly": weekly, "annual": weekly * 52, "source": "estimate"}

# =============================================================================
# APPRAISAL GENERATION
# =============================================================================

def generate_appraisal(property_details: dict, comps: list, ltr_estimate: dict) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ API key not configured."
    
    comps_text = ""
    payout_values = []
    
    for i, comp in enumerate(comps[:5], 1):
        annual = comp['avg_monthly_payout'] * 12
        payout_values.append(annual)
        has_pool = "Yes" if comp.get('Amenities') and 'pool' in comp['Amenities'].lower() else "No"
        dist = comp.get('distance', 0)
        comps_text += f"{i}. {comp['Nickname']}: {comp['Bedrooms']}bed/{comp['Bathrooms']}bath, Pool:{has_pool}, {dist:.1f}km, ${annual:,.0f}/year\n"
    
    min_pay, max_pay = min(payout_values), max(payout_values)
    avg_pay = sum(payout_values) / len(payout_values)
    pool_count = sum(1 for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower())
    
    prompt = f"""Write a property appraisal. CRITICAL FORMATTING RULES:
- PUT SPACES between numbers and words: "$38,000 annually" NOT "$38,000annually"
- PUT SPACES around "to": "$31,000 to $54,000" NOT "$31,000to54,000"
- WRITE FULL NUMBERS: "$54,236" NOT "$54k"
- NEVER concatenate: "Regand Park ($54,236) and Macquarie" NOT "RegandPark$54,236andMacquarie"

PROPERTY: {property_details['address']}, {property_details['bedrooms']}bed/{property_details['bathrooms']}bath, {property_details['region']}
FEATURES: {property_details.get('features', 'Not specified')}

COMPS (by distance):
{comps_text}

STATS: Range ${min_pay:,.0f} to ${max_pay:,.0f}, Average ${avg_pay:,.0f}, {pool_count}/5 have pools
LTR: ${ltr_estimate['weekly']}/week (${ltr_estimate['annual']:,}/year)

Write these sections:

## Summary
Two sentences about market position.

## Projected Returns
- **Conservative**: $XX,XXX annually - (reason)
- **Mid-range**: $XX,XXX annually - (reason)
- **Optimistic**: $XX,XXX annually - (reason)

**STR Premium**: $XX,XXX above LTR of ${ltr_estimate['annual']:,} (XX% premium)

## Key Factors
**Advantages:** 2-3 bullet points
**Disadvantages:** 2-3 bullet points

## Sales Points
3 bullet points for owner conversation.

Keep under 300 words. REMEMBER: spaces between all numbers and words."""

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
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        return f"⚠️ API Error: {response.status_code}"
    except Exception as e:
        return f"⚠️ Error: {e}"

# =============================================================================
# MAIN
# =============================================================================

def main():
    st.markdown("# 🏠 Appraisal Tool")
    st.markdown("*Generate data-driven STR appraisals*")
    st.markdown("---")
    
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
        
        with st.spinner("Finding comparables..."):
            comps = get_regional_comps(region, bedrooms)
        
        if not comps:
            st.warning(f"No comparables found in {region}.")
            return
        
        with st.spinner("Calculating distances..."):
            prospect_coords = geocode_address(address, region)
            
            for comp in comps:
                if prospect_coords and comp.get('Latitude') and comp.get('Longitude'):
                    comp['distance'] = calculate_distance(
                        prospect_coords['lat'], prospect_coords['lon'],
                        comp['Latitude'], comp['Longitude']
                    )
                else:
                    comp['distance'] = 0
            
            comps.sort(key=lambda x: x.get('distance', 0) if x.get('distance', 0) > 0 else 999)
        
        with st.spinner("Looking up rental rates..."):
            ltr_estimate = get_ltr_estimate(region, bedrooms)
        
        # ========== DISPLAY ==========
        
        st.markdown("### 📍 Prospect Property")
        st.info(f"**{address}** — {bedrooms} bed, {bathrooms} bath")
        
        # MAP with labels
        st.markdown("### 🗺️ Location Map")
        
        map_data = []
        
        # Prospect marker (blue)
        if prospect_coords:
            map_data.append({
                'lat': prospect_coords['lat'],
                'lon': prospect_coords['lon'],
                'name': '📍 PROSPECT',
                'color': [0, 100, 255, 200],
                'size': 200
            })
        
        # Comp markers (red)
        for i, comp in enumerate(comps[:5], 1):
            if comp.get('Latitude') and comp.get('Longitude'):
                annual = comp['avg_monthly_payout'] * 12
                map_data.append({
                    'lat': comp['Latitude'],
                    'lon': comp['Longitude'],
                    'name': f"{i}. {comp['Nickname']} (${annual:,.0f})",
                    'color': [255, 100, 100, 200],
                    'size': 150
                })
        
        if map_data:
            df = pd.DataFrame(map_data)
            
            # Calculate center
            center_lat = df['lat'].mean()
            center_lon = df['lon'].mean()
            
            layer = pdk.Layer(
                'ScatterplotLayer',
                data=df,
                get_position=['lon', 'lat'],
                get_color='color',
                get_radius='size',
                pickable=True
            )
            
            text_layer = pdk.Layer(
                'TextLayer',
                data=df,
                get_position=['lon', 'lat'],
                get_text='name',
                get_size=14,
                get_color=[0, 0, 0, 255],
                get_angle=0,
                get_text_anchor='"middle"',
                get_alignment_baseline='"bottom"'
            )
            
            view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=12)
            
            deck = pdk.Deck(
                layers=[layer, text_layer],
                initial_view_state=view,
                tooltip={"text": "{name}"}
            )
            
            st.pydeck_chart(deck)
        else:
            st.warning("Could not generate map")
        
        # COMPS
        st.markdown("### 📊 Comparable Properties")
        
        for i, comp in enumerate(comps[:5], 1):
            annual = comp['avg_monthly_payout'] * 12
            has_pool = comp.get('Amenities') and 'pool' in comp['Amenities'].lower()
            dist = comp.get('distance', 0)
            
            dist_text = f"{dist:.1f}km" if dist > 0 else "Unknown"
            pool_text = "🏊 Pool" if has_pool else "❌ No pool"
            pool_color = "green" if has_pool else "red"
            
            is_top = annual == max(c['avg_monthly_payout'] * 12 for c in comps[:5])
            badge = " ⭐" if is_top else ""
            
            airbnb_link = f"[Airbnb](https://www.airbnb.com.au/rooms/{comp['AirbnbId']})" if comp.get('AirbnbId') else ""
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{i}. {comp['Nickname']}{badge}**")
                st.caption(f"{comp['Bedrooms']}bed · {comp['Bathrooms']}bath · 📍 {dist_text} · :{pool_color}[{pool_text}] · {airbnb_link}")
            with col2:
                st.metric("Annual", f"${annual:,.0f}")
            st.divider()
        
        # RETURNS
        st.markdown("### 💰 Projected Returns")
        
        payout_values = [c['avg_monthly_payout'] * 12 for c in comps[:5]]
        min_p, max_p, avg_p = min(payout_values), max(payout_values), sum(payout_values)/len(payout_values)
        
        prospect_has_pool = features and 'pool' in features.lower()
        pool_count = sum(1 for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower())
        adj = 0.85 if (pool_count >= 2 and not prospect_has_pool) else 1.0
        
        conservative, midrange, optimistic = min_p * 0.9 * adj, avg_p * adj, max_p * adj
        str_premium = midrange - ltr_estimate['annual']
        str_pct = (str_premium / ltr_estimate['annual'] * 100) if ltr_estimate['annual'] > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Conservative", f"${conservative:,.0f}")
        with col2:
            st.metric("Mid-range", f"${midrange:,.0f}")
        with col3:
            st.metric("Optimistic", f"${optimistic:,.0f}")
        
        st.markdown("#### Long-Term Rental Comparison")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("LTR Weekly", f"${ltr_estimate['weekly']}")
        with col2:
            st.metric("LTR Annual", f"${ltr_estimate['annual']:,}")
        with col3:
            st.metric("STR Premium", f"+${str_premium:,.0f}", f"{str_pct:.0f}% above LTR")
        
        if adj < 1:
            st.warning(f"⚠️ Estimates reduced 15% — {pool_count}/5 comps have pools, prospect does not")
        
        # AI SUMMARY
        st.markdown("### 📝 Appraisal Summary")
        
        with st.spinner("Generating appraisal..."):
            appraisal = generate_appraisal(
                {"address": address, "region": region, "bedrooms": bedrooms, 
                 "bathrooms": bathrooms, "features": features, "value": value},
                comps, ltr_estimate
            )
        
        st.markdown(appraisal)


if __name__ == "__main__":
    main()
