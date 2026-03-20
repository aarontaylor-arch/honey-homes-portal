"""
Appraisal Tool v3.1
Fixed: HTML rendering, decimal types, geocoding
"""

import streamlit as st
import pymssql
import requests
import os
import math
import json
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

# LTR weekly rental estimates by region and bedrooms
LTR_ESTIMATES = {
    "Wagga Wagga": {2: 380, 3: 450, 4: 550, 5: 650},
    "Orange": {2: 350, 3: 420, 4: 500, 5: 600},
    "Bathurst": {2: 360, 3: 430, 4: 520, 5: 620},
    "Dubbo": {2: 340, 3: 400, 4: 480, 5: 580},
}

# Regional center coordinates (fallback for geocoding)
REGION_COORDS = {
    "Wagga Wagga": {"lat": -35.1082, "lon": 147.3598},
    "Orange": {"lat": -33.2836, "lon": 149.1013},
    "Bathurst": {"lat": -33.4196, "lon": 149.5777},
    "Dubbo": {"lat": -32.2569, "lon": 148.6011},
}

# =============================================================================
# HELPER FUNCTION - Convert Decimal to float
# =============================================================================

def to_float(val):
    """Convert Decimal or any numeric to float, handling None."""
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
# GEOCODING FUNCTIONS
# =============================================================================

def geocode_address(address: str, region: str = None) -> dict:
    """Geocode an address using OpenStreetMap Nominatim."""
    if not address:
        return None
    
    # Clean up address - add state if not present
    if "NSW" not in address.upper() and "NEW SOUTH WALES" not in address.upper():
        address = f"{address}, NSW, Australia"
    elif "Australia" not in address:
        address = f"{address}, Australia"
    
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": address,
                "format": "json",
                "limit": 1,
                "countrycodes": "au"
            },
            headers={"User-Agent": "AppraisalTool/1.0"},
            timeout=5
        )
        
        if response.status_code == 200 and response.json():
            result = response.json()[0]
            return {
                "lat": float(result["lat"]),
                "lon": float(result["lon"]),
                "found": True
            }
    except Exception as e:
        pass
    
    # Fallback to region center if geocoding fails
    if region and region in REGION_COORDS:
        coords = REGION_COORDS[region]
        return {
            "lat": coords["lat"],
            "lon": coords["lon"],
            "found": False
        }
    
    return None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers."""
    R = 6371
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


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
    """Get comparable properties from the same region."""
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
        # Convert Decimals to floats
        for r in results:
            r['avg_monthly_payout'] = to_float(r.get('avg_monthly_payout'))
            r['avg_monthly_gross'] = to_float(r.get('avg_monthly_gross'))
            r['avg_nights'] = to_float(r.get('avg_nights'))
            r['total_owner_payout'] = to_float(r.get('total_owner_payout'))
            r['total_gross_revenue'] = to_float(r.get('total_gross_revenue'))
            if r.get('Latitude'):
                r['Latitude'] = to_float(r['Latitude'])
            if r.get('Longitude'):
                r['Longitude'] = to_float(r['Longitude'])
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
        output = {}
        for r in results:
            r['avg_monthly_payout'] = to_float(r.get('avg_monthly_payout'))
            r['avg_monthly_gross'] = to_float(r.get('avg_monthly_gross'))
            r['avg_nights'] = to_float(r.get('avg_nights'))
            output[r['Bedrooms']] = r
        return output
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
# CLAUDE APPRAISAL GENERATION
# =============================================================================

def generate_appraisal(property_details: dict, comps: list, ltr_estimate: dict) -> str:
    """Use Claude to generate the appraisal summary."""
    
    if not ANTHROPIC_API_KEY:
        return "⚠️ API key not configured."
    
    # Build comps text
    comps_text = ""
    payout_values = []
    
    for i, comp in enumerate(comps[:5], 1):
        annual_payout = comp['avg_monthly_payout'] * 12
        annual_gross = comp['avg_monthly_gross'] * 12
        avg_nights = comp['avg_nights']
        payout_values.append(annual_payout)
        
        has_pool = "Yes" if comp.get('Amenities') and 'pool' in comp['Amenities'].lower() else "No"
        distance = comp.get('distance', 0)
        distance_str = f"{distance:.1f}km" if distance < 100 else "Unknown"
        
        comps_text += f"""
Comp {i}: {comp['Nickname']}
- Distance: {distance_str}
- Config: {comp['Bedrooms']} bed / {comp['Bathrooms']} bath
- Pool: {has_pool}
- Annual Payout: ${annual_payout:,.0f}
- Annual Gross: ${annual_gross:,.0f}
- Avg nights/month: {avg_nights:.0f}
- Airbnb: https://www.airbnb.com.au/rooms/{comp.get('AirbnbId', '')}
"""
    
    min_payout = min(payout_values) if payout_values else 0
    max_payout = max(payout_values) if payout_values else 0
    avg_payout = sum(payout_values) / len(payout_values) if payout_values else 0
    
    pool_count = sum(1 for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower())
    
    prompt = f"""Generate a concise STR appraisal for this property.

PROSPECT:
- Address: {property_details['address']}
- Region: {property_details['region']}  
- Config: {property_details['bedrooms']} bed / {property_details['bathrooms']} bath
- Features: {property_details.get('features', 'Not specified')}

COMPARABLES:
{comps_text}

STATS:
- {pool_count}/5 comps have pools
- Payout range: ${min_payout:,.0f} - ${max_payout:,.0f}
- Average: ${avg_payout:,.0f}
- LTR estimate: ${ltr_estimate['weekly']}/week (${ltr_estimate['annual']:,}/year)

Write a brief appraisal with:
1. **Summary** (2 sentences)
2. **Projected Returns** - Conservative/Mid/Optimistic scenarios with specific $ amounts. Show STR premium over LTR.
3. **Key Factors** - Top 3 advantages and disadvantages vs comps
4. **Sales Points** - 3 bullet points for owner conversation

Keep it under 400 words. Be conservative with estimates."""

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
        else:
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
            placeholder="Pool, renovation, views, etc.",
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
            annual_payout = avg['avg_monthly_payout'] * 12
            str_premium = annual_payout - ltr['annual']
            
            st.markdown(f"""
            <div class="metric-card">
                <strong>{bedrooms}-bed in {region}</strong><br><br>
                📊 <strong>{avg['property_count']}</strong> properties<br>
                💰 <strong>${annual_payout:,.0f}</strong>/year STR<br>
                🏠 <strong>${ltr['annual']:,}</strong>/year LTR<br>
                📈 <strong>+${str_premium:,.0f}</strong> STR premium
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Generate Button
    if st.button("🔍 Generate Appraisal", use_container_width=True):
        if not address:
            st.warning("Please enter a property address.")
            return
        
        with st.spinner("Finding comparable properties..."):
            comps = get_regional_comps(region, bedrooms)
        
        if not comps:
            st.warning(f"No comparable properties found in {region}.")
            return
        
        with st.spinner("Calculating distances..."):
            # Geocode prospect
            prospect_coords = geocode_address(address, region)
            
            # Calculate distances for comps
            for comp in comps:
                comp_lat = comp.get('Latitude')
                comp_lon = comp.get('Longitude')
                
                if prospect_coords and comp_lat and comp_lon:
                    comp['distance'] = calculate_distance(
                        prospect_coords['lat'], prospect_coords['lon'],
                        comp_lat, comp_lon
                    )
                else:
                    # Try geocoding the comp address
                    comp_addr = comp.get('FullAddress') or comp.get('StreetAddress')
                    if comp_addr and prospect_coords:
                        comp_coords = geocode_address(comp_addr, region)
                        if comp_coords:
                            comp['distance'] = calculate_distance(
                                prospect_coords['lat'], prospect_coords['lon'],
                                comp_coords['lat'], comp_coords['lon']
                            )
                        else:
                            comp['distance'] = 0
                    else:
                        comp['distance'] = 0
            
            # Sort by distance (0 means unknown, put at end)
            comps.sort(key=lambda x: x.get('distance', 0) if x.get('distance', 0) > 0 else 999)
        
        ltr_estimate = get_ltr_estimate(region, bedrooms)
        
        # =================================================================
        # DISPLAY RESULTS
        # =================================================================
        
        # Prospect Card
        st.markdown("### 📍 Prospect Property")
        st.info(f"**{address}** — {bedrooms} bed, {bathrooms} bath")
        
        # Comparable Properties
        st.markdown("### 📊 Comparable Properties")
        
        for i, comp in enumerate(comps[:5], 1):
            annual_payout = comp['avg_monthly_payout'] * 12
            annual_gross = comp['avg_monthly_gross'] * 12
            has_pool = comp.get('Amenities') and 'pool' in comp['Amenities'].lower()
            distance = comp.get('distance', 0)
            
            # Format distance
            if distance > 0 and distance < 100:
                dist_text = f"📍 {distance:.1f}km away"
            else:
                dist_text = "📍 Distance unknown"
            
            # Pool badge
            pool_text = "🏊 Pool" if has_pool else "No pool"
            pool_color = "green" if has_pool else "red"
            
            # Top performer badge
            is_top = (i == 1) or (annual_payout == max(c['avg_monthly_payout'] * 12 for c in comps[:5]))
            top_badge = " ⭐ Top Performer" if is_top else ""
            
            # Airbnb link
            airbnb_id = comp.get('AirbnbId')
            airbnb_link = f"[View on Airbnb](https://www.airbnb.com.au/rooms/{airbnb_id})" if airbnb_id else ""
            
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{i}. {comp['Nickname']}**{top_badge}")
                    st.caption(f"{comp['Bedrooms']} bed · {comp['Bathrooms']} bath · {dist_text} · :{pool_color}[{pool_text}]")
                    st.caption(f"{comp['months_of_data']} months data · {comp['avg_nights']:.0f} nights/month · {airbnb_link}")
                with col2:
                    st.metric("Annual Payout", f"${annual_payout:,.0f}")
                
                st.divider()
        
        # Projected Returns
        st.markdown("### 💰 Projected Returns")
        
        payout_values = [c['avg_monthly_payout'] * 12 for c in comps[:5]]
        min_payout = min(payout_values)
        max_payout = max(payout_values)
        avg_payout = sum(payout_values) / len(payout_values)
        
        # Check if prospect likely has pool (from features input)
        prospect_has_pool = features and 'pool' in features.lower()
        pool_count = sum(1 for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower())
        
        # Apply adjustment if no pool but comps have pools
        adjustment = 0.85 if (pool_count >= 2 and not prospect_has_pool) else 1.0
        
        conservative = min_payout * 0.9 * adjustment
        midrange = avg_payout * adjustment
        optimistic = max_payout * adjustment
        
        str_premium = midrange - ltr_estimate['annual']
        str_premium_pct = (str_premium / ltr_estimate['annual'] * 100) if ltr_estimate['annual'] > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Conservative", f"${conservative:,.0f}", help="Based on lowest comp minus 10%")
        with col2:
            st.metric("Mid-range", f"${midrange:,.0f}", help="Average of comparables")
        with col3:
            st.metric("Optimistic", f"${optimistic:,.0f}", help="Top performer level")
        
        st.success(f"**STR Premium over LTR: +${str_premium:,.0f}/year ({str_premium_pct:.0f}% above ${ltr_estimate['annual']:,} LTR)**")
        
        if adjustment < 1:
            st.warning(f"⚠️ Estimates reduced by 15% — {pool_count} of 5 comps have pools but prospect does not")
        
        # AI Appraisal
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
