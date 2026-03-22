"""
Appraisal Tool v3.6
- Manual LTR input from user
- No web search dependency
- Clean structured output
"""

import streamlit as st
import pymssql
import requests
import os
import math
import pandas as pd
import pydeck as pdk
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
    
    .summary-box {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 0.5rem 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    
    .advantage-item {
        background: #F0FDF4;
        border-left: 4px solid #10B981;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
    }
    
    .disadvantage-item {
        background: #FEF2F2;
        border-left: 4px solid #EF4444;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
    }
    
    .sales-point {
        background: #EFF6FF;
        border-left: 4px solid #3B82F6;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
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
# ANALYSIS FUNCTIONS
# =============================================================================

def analyze_property(property_details: dict, comps: list, ltr_weekly: int) -> dict:
    """Analyze property and generate structured insights."""
    
    region = property_details['region']
    bedrooms = property_details['bedrooms']
    bathrooms = property_details['bathrooms']
    
    ltr_annual = ltr_weekly * 52
    
    payout_values = [c['avg_monthly_payout'] * 12 for c in comps[:5]]
    min_pay = min(payout_values) if payout_values else 0
    max_pay = max(payout_values) if payout_values else 0
    avg_pay = sum(payout_values) / len(payout_values) if payout_values else 0
    
    # Pool analysis
    pool_comps = [c for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower()]
    pool_count = len(pool_comps)
    prospect_has_pool = property_details.get('features') and 'pool' in property_details['features'].lower()
    
    # Adjustment factor
    adjustment = 0.85 if (pool_count >= 2 and not prospect_has_pool) else 1.0
    
    # Calculate projections
    conservative = min_pay * 0.9 * adjustment
    midrange = avg_pay * adjustment
    optimistic = max_pay * adjustment
    
    # STR premium
    str_premium = midrange - ltr_annual
    str_premium_pct = (str_premium / ltr_annual * 100) if ltr_annual > 0 else 0
    
    # Find top performer
    top_comp = max(comps[:5], key=lambda c: c['avg_monthly_payout']) if comps else None
    top_comp_annual = top_comp['avg_monthly_payout'] * 12 if top_comp else 0
    
    # Average nights
    avg_nights = sum(c['avg_nights'] for c in comps[:5]) / len(comps[:5]) if comps else 0
    
    # Build advantages
    advantages = []
    
    if bathrooms >= bedrooms:
        advantages.append(f"{bathrooms} bathrooms with {bedrooms} bedrooms — premium 1:1 ratio appeals to families and groups")
    elif bathrooms >= 2:
        advantages.append(f"{bathrooms} bathrooms — good capacity for guest comfort")
    
    if bedrooms == 4:
        advantages.append("4-bedroom sweet spot — large enough for groups, not oversized for couples")
    elif bedrooms >= 5:
        advantages.append(f"{bedrooms} bedrooms — appeals to large family gatherings and group bookings")
    
    if avg_nights >= 20:
        advantages.append(f"Strong local market — comps average {avg_nights:.0f} nights/month occupancy")
    
    if prospect_has_pool:
        advantages.append("Pool — matches top performers and commands premium rates")
    
    # Build disadvantages
    disadvantages = []
    
    if pool_count >= 2 and not prospect_has_pool:
        pool_comp_names = [c['Nickname'] for c in pool_comps[:2]]
        pool_comp_payouts = [f"${c['avg_monthly_payout']*12:,.0f}" for c in pool_comps[:2]]
        if len(pool_comp_names) >= 2:
            disadvantages.append(f"No pool — top performers {pool_comp_names[0]} ({pool_comp_payouts[0]}) and {pool_comp_names[1]} ({pool_comp_payouts[1]}) have pools")
        elif len(pool_comp_names) == 1:
            disadvantages.append(f"No pool — top performer {pool_comp_names[0]} ({pool_comp_payouts[0]}) has a pool")
    
    if bathrooms > 2:
        disadvantages.append(f"{bathrooms} bathrooms increases cleaning time and turnover costs")
    
    closest_comp = comps[0] if comps else None
    if closest_comp and closest_comp.get('distance', 0) < 2:
        nearby_count = len([c for c in comps[:5] if c.get('distance', 0) < 2])
        if nearby_count > 1:
            disadvantages.append(f"Competitive area — {nearby_count} established STRs within 2km")
    
    if not disadvantages:
        disadvantages.append("New listing will need time to build reviews and optimise pricing")
    
    # Build sales points
    sales_points = []
    
    sales_points.append(f"STR delivers ${str_premium:,.0f} more per year than long-term rental — that's {str_premium_pct:.0f}% extra income")
    
    if bathrooms >= bedrooms:
        sales_points.append(f"Your {bathrooms} bathrooms eliminate the #1 guest complaint — bathroom queues. This drives 5-star reviews.")
    
    sales_points.append(f"Our {region} properties average {avg_nights:.0f} nights booked per month with consistent demand year-round")
    
    if conservative > ltr_annual:
        sales_points.append(f"Even our conservative estimate of ${conservative:,.0f} beats traditional rental by ${conservative - ltr_annual:,.0f}")
    
    return {
        "conservative": conservative,
        "midrange": midrange,
        "optimistic": optimistic,
        "ltr_weekly": ltr_weekly,
        "ltr_annual": ltr_annual,
        "str_premium": str_premium,
        "str_premium_pct": str_premium_pct,
        "adjustment": adjustment,
        "pool_count": pool_count,
        "prospect_has_pool": prospect_has_pool,
        "advantages": advantages[:3],
        "disadvantages": disadvantages[:3],
        "sales_points": sales_points[:4],
        "top_comp": top_comp,
        "top_comp_annual": top_comp_annual,
        "min_pay": min_pay,
        "max_pay": max_pay,
        "avg_pay": avg_pay,
        "avg_nights": avg_nights
    }

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
        
        col_d, col_e = st.columns(2)
        with col_d:
            value = st.text_input("Property Value (optional)", placeholder="e.g., $750,000")
        with col_e:
            ltr_weekly = st.number_input(
                "LTR Weekly Rent ($)", 
                min_value=200, 
                max_value=2000, 
                value=550,
                help="Check domain.com.au for current rental rates"
            )
    
    with col2:
        st.markdown("### Quick Stats")
        averages = get_region_averages(region)
        if bedrooms in averages:
            avg = averages[bedrooms]
            annual_payout = avg['avg_monthly_payout'] * 12
            ltr_annual = ltr_weekly * 52
            str_premium = annual_payout - ltr_annual
            
            st.markdown(f"""
            <div class="metric-card">
                <strong>{bedrooms}-bed in {region}</strong><br><br>
                📊 <strong>{avg['property_count']}</strong> properties<br>
                💰 <strong>${annual_payout:,.0f}</strong>/year STR<br>
                🏠 <strong>${ltr_weekly}/week</strong> LTR (${ltr_annual:,}/yr)<br>
                📈 <strong>+${str_premium:,.0f}</strong> STR premium
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.caption("💡 Check [domain.com.au](https://www.domain.com.au/rent/) for current LTR rates")
    
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
        
        # Analyze
        property_details = {
            "address": address, "region": region, 
            "bedrooms": bedrooms, "bathrooms": bathrooms,
            "features": features, "value": value
        }
        analysis = analyze_property(property_details, comps, ltr_weekly)
        
        # ========== DISPLAY ==========
        
        st.markdown("### 📍 Prospect Property")
        st.info(f"**{address}** — {bedrooms} bed, {bathrooms} bath")
        
        # MAP
        st.markdown("### 🗺️ Location Map")
        
        map_data = []
        if prospect_coords:
            map_data.append({
                'lat': prospect_coords['lat'], 'lon': prospect_coords['lon'],
                'name': '📍 PROSPECT', 'color': [0, 100, 255, 200], 'size': 200
            })
        
        for i, comp in enumerate(comps[:5], 1):
            if comp.get('Latitude') and comp.get('Longitude'):
                annual = comp['avg_monthly_payout'] * 12
                map_data.append({
                    'lat': comp['Latitude'], 'lon': comp['Longitude'],
                    'name': f"{i}. {comp['Nickname']} (${annual:,.0f})",
                    'color': [255, 100, 100, 200], 'size': 150
                })
        
        if map_data:
            df = pd.DataFrame(map_data)
            center_lat, center_lon = df['lat'].mean(), df['lon'].mean()
            
            layer = pdk.Layer(
                'ScatterplotLayer', data=df,
                get_position=['lon', 'lat'], get_color='color', get_radius='size', pickable=True
            )
            text_layer = pdk.Layer(
                'TextLayer', data=df,
                get_position=['lon', 'lat'], get_text='name', get_size=12,
                get_color=[0, 0, 0, 255], get_text_anchor='"middle"', get_alignment_baseline='"bottom"'
            )
            
            st.pydeck_chart(pdk.Deck(
                layers=[layer, text_layer],
                initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=12),
                tooltip={"text": "{name}"}
            ))
        
        # COMPS
        st.markdown("### 📊 Comparable Properties")
        
        for i, comp in enumerate(comps[:5], 1):
            annual = comp['avg_monthly_payout'] * 12
            has_pool = comp.get('Amenities') and 'pool' in comp['Amenities'].lower()
            dist = comp.get('distance', 0)
            
            dist_text = f"{dist:.1f}km" if dist > 0 else "Unknown"
            pool_text = "🏊 Pool" if has_pool else "❌ No pool"
            pool_color = "green" if has_pool else "red"
            
            is_top = annual == analysis['top_comp_annual']
            badge = " ⭐" if is_top else ""
            
            airbnb_link = f"[Airbnb](https://www.airbnb.com.au/rooms/{comp['AirbnbId']})" if comp.get('AirbnbId') else ""
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{i}. {comp['Nickname']}{badge}**")
                st.caption(f"{comp['Bedrooms']}bed · {comp['Bathrooms']}bath · 📍 {dist_text} · :{pool_color}[{pool_text}] · {airbnb_link}")
            with col2:
                st.metric("Annual", f"${annual:,.0f}")
            st.divider()
        
        # PROJECTED RETURNS
        st.markdown("### 💰 Projected Returns")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Conservative", f"${analysis['conservative']:,.0f}", 
                     help="Based on lowest performing comp minus 10%")
        with col2:
            st.metric("Mid-range", f"${analysis['midrange']:,.0f}", 
                     help="Based on average of comparable properties")
        with col3:
            st.metric("Optimistic", f"${analysis['optimistic']:,.0f}", 
                     help="Achievable if matching top performer")
        
        # LTR COMPARISON
        st.markdown("#### Long-Term Rental Comparison")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("LTR Weekly", f"${analysis['ltr_weekly']}")
        with col2:
            st.metric("LTR Annual", f"${analysis['ltr_annual']:,}")
        with col3:
            st.metric("STR Premium", f"+${analysis['str_premium']:,.0f}", 
                     f"{analysis['str_premium_pct']:.0f}% above LTR")
        
        if analysis['adjustment'] < 1:
            st.warning(f"⚠️ Estimates reduced 15% — {analysis['pool_count']}/5 comps have pools, prospect does not")
        
        # ADVANTAGES
        st.markdown("### ✅ Advantages")
        for adv in analysis['advantages']:
            st.markdown(f"""<div class="advantage-item">{adv}</div>""", unsafe_allow_html=True)
        
        # DISADVANTAGES
        st.markdown("### ⚠️ Considerations")
        for dis in analysis['disadvantages']:
            st.markdown(f"""<div class="disadvantage-item">{dis}</div>""", unsafe_allow_html=True)
        
        # SALES POINTS
        st.markdown("### 💬 Sales Talking Points")
        for point in analysis['sales_points']:
            st.markdown(f"""<div class="sales-point">"{point}"</div>""", unsafe_allow_html=True)
        
        # SUMMARY BOX
        st.markdown("### 📋 Summary")
        st.markdown(f"""
        <div class="summary-box">
            <strong>Property:</strong> {address}<br>
            <strong>Configuration:</strong> {bedrooms} bed / {bathrooms} bath<br>
            <strong>Comparable Range:</strong> ${analysis['min_pay']:,.0f} – ${analysis['max_pay']:,.0f} per year<br>
            <strong>Recommended Quote:</strong> ${analysis['midrange']:,.0f} per year (mid-range)<br>
            <strong>STR vs LTR:</strong> +${analysis['str_premium']:,.0f} ({analysis['str_premium_pct']:.0f}% premium over ${analysis['ltr_annual']:,} LTR)<br>
            <strong>Market Occupancy:</strong> {analysis['avg_nights']:.0f} nights/month average
        </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
