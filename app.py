"""
Appraisal Tool v3.7
- Seasonality chart with monthly projections
- YoY growth adjustments
- Stronger sales talking points
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

# Seasonality by region (% of annual revenue per month)
SEASONALITY = {
    "Dubbo": [0.07, 0.09, 0.06, 0.11, 0.07, 0.09, 0.09, 0.08, 0.10, 0.11, 0.06, 0.07],
    "Bathurst": [0.06, 0.09, 0.05, 0.13, 0.09, 0.08, 0.06, 0.05, 0.07, 0.18, 0.09, 0.06],
    "Orange": [0.06, 0.06, 0.09, 0.12, 0.07, 0.10, 0.08, 0.07, 0.08, 0.11, 0.08, 0.08],
    "Wagga Wagga": [0.06, 0.10, 0.06, 0.11, 0.09, 0.08, 0.08, 0.08, 0.11, 0.10, 0.07, 0.08],
}

# Year-on-year growth rates
YOY_GROWTH = {
    "Dubbo": 0.245,      # 24.5%
    "Bathurst": -0.1029, # -10.29%
    "Orange": 0.0256,    # 2.56%
    "Wagga Wagga": 0.103 # 10.3%
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

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
        font-size: 1.05rem;
    }
    
    .growth-positive {
        color: #059669;
        font-weight: 600;
    }
    
    .growth-negative {
        color: #DC2626;
        font-weight: 600;
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
# SEASONALITY & PROJECTIONS
# =============================================================================

def get_monthly_projections(annual_amount: float, region: str, apply_growth: bool = True) -> list:
    """Calculate monthly projections based on seasonality and optional YoY growth."""
    seasonality = SEASONALITY.get(region, [1/12] * 12)
    growth = YOY_GROWTH.get(region, 0) if apply_growth else 0
    
    # Apply growth (capped at reasonable levels)
    growth = max(-0.15, min(0.30, growth))  # Cap between -15% and +30%
    adjusted_annual = annual_amount * (1 + growth)
    
    monthly = [adjusted_annual * s for s in seasonality]
    return monthly, adjusted_annual, growth

# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================

def analyze_property(property_details: dict, comps: list, ltr_weekly: int) -> dict:
    """Analyze property and generate structured insights."""
    
    region = property_details['region']
    bedrooms = property_details['bedrooms']
    bathrooms = property_details['bathrooms']
    
    ltr_annual = ltr_weekly * 52
    ltr_agent_fee = 0.06  # 6% agent fee
    ltr_annual_net = ltr_annual * (1 - ltr_agent_fee)
    ltr_monthly = ltr_annual_net / 12
    
    payout_values = [c['avg_monthly_payout'] * 12 for c in comps[:5]]
    min_pay = min(payout_values) if payout_values else 0
    max_pay = max(payout_values) if payout_values else 0
    avg_pay = sum(payout_values) / len(payout_values) if payout_values else 0
    
    # Pool analysis
    pool_comps = [c for c in comps[:5] if c.get('Amenities') and 'pool' in c['Amenities'].lower() and 'pool table' not in c['Amenities'].lower()]
    pool_count = len(pool_comps)
    prospect_has_pool = property_details.get('features') and 'pool' in property_details['features'].lower()
    
    # Adjustment factor for no pool
    pool_adjustment = 0.85 if (pool_count >= 2 and not prospect_has_pool) else 1.0
    
    # Base projections (before growth)
    conservative_base = min_pay * 0.9 * pool_adjustment
    midrange_base = avg_pay * pool_adjustment
    optimistic_base = max_pay * pool_adjustment
    
    # Apply YoY growth
    growth_rate = YOY_GROWTH.get(region, 0)
    growth_rate = max(-0.15, min(0.30, growth_rate))  # Cap it
    
    conservative = conservative_base * (1 + growth_rate)
    midrange = midrange_base * (1 + growth_rate)
    optimistic = optimistic_base * (1 + growth_rate)
    
    # Monthly projections for chart - apply growth on top of adjusted figures
    seasonality = SEASONALITY.get(region, [1/12] * 12)
    chart_annual_mid = midrange * (1 + growth_rate)
    chart_annual_high = optimistic * (1 + growth_rate)
    monthly_mid = [chart_annual_mid * s for s in seasonality]
    monthly_high = [chart_annual_high * s for s in seasonality]
    
    # STR premium (compared to net LTR after agent fees)
    str_premium = midrange - ltr_annual_net
    str_premium_pct = (str_premium / ltr_annual_net * 100) if ltr_annual_net > 0 else 0
    
    # Find top performer
    top_comp = max(comps[:5], key=lambda c: c['avg_monthly_payout']) if comps else None
    top_comp_annual = top_comp['avg_monthly_payout'] * 12 if top_comp else 0
    
    # Average nights
    avg_nights = sum(c['avg_nights'] for c in comps[:5]) / len(comps[:5]) if comps else 0
    
    # Build advantages
    advantages = []
    
    if bathrooms >= bedrooms:
        advantages.append(f"{bathrooms} bathrooms with {bedrooms} bedrooms — premium 1:1 ratio that families pay more for")
    elif bathrooms >= 2:
        advantages.append(f"{bathrooms} bathrooms — handles group bookings without complaints")
    
    if growth_rate > 0.05:
        advantages.append(f"{region} market growing {growth_rate*100:.0f}% year-on-year — your returns will increase")
    
    if bedrooms == 4:
        advantages.append("4-bedroom sweet spot — large enough for groups, not too big to fill midweek")
    elif bedrooms >= 5:
        advantages.append(f"{bedrooms} bedrooms — premium for large family gatherings and group bookings")
    
    if avg_nights >= 20:
        advantages.append(f"Proven demand — our {region} properties book {avg_nights:.0f} nights/month consistently")
    
    if prospect_has_pool:
        advantages.append("Pool puts you in the top tier — our pool properties earn 15-20% more")
    
    # Build disadvantages
    disadvantages = []
    
    if pool_count >= 2 and not prospect_has_pool:
        top_pool = pool_comps[0]
        disadvantages.append(f"No pool — {top_pool['Nickname']} with pool earns ${top_pool['avg_monthly_payout']*12:,.0f}/year")
    
    if growth_rate < -0.05:
        disadvantages.append(f"{region} market down {abs(growth_rate)*100:.0f}% year-on-year — factored into projections")
    
    if bathrooms > 2:
        disadvantages.append(f"{bathrooms} bathrooms = longer turnovers (~$30-50 extra per clean)")
    
    closest_comp = comps[0] if comps else None
    if closest_comp and closest_comp.get('distance', 0) < 1.5:
        nearby_count = len([c for c in comps[:5] if c.get('distance', 0) < 2])
        if nearby_count >= 3:
            disadvantages.append(f"{nearby_count} established competitors within 2km — need strong listing to stand out")
    
    if not disadvantages:
        disadvantages.append("New listing needs 3-6 months to build reviews and optimise pricing")
    
    # Build STRONG sales points
    sales_points = []
    
    # The money shot
    if str_premium > 10000:
        sales_points.append(f"You're leaving ${str_premium:,.0f} on the table every year with long-term rental")
    else:
        sales_points.append(f"STR earns you ${str_premium:,.0f} more per year — that's {str_premium_pct:.0f}% extra in your pocket")
    
    # Peak season hook
    seasonality = SEASONALITY.get(region, [1/12] * 12)
    peak_month_idx = seasonality.index(max(seasonality))
    peak_month = MONTHS[peak_month_idx]
    peak_monthly = monthly_high[peak_month_idx]
    sales_points.append(f"In {peak_month} alone, top performers earn ${peak_monthly:,.0f} — that's more than 2 months of rent")
    
    # Growth story (if positive)
    if growth_rate > 0.05:
        next_year = midrange * (1 + growth_rate)
        sales_points.append(f"{region} STR is booming — at current growth, you'd earn ${next_year:,.0f} by year two")
    
    # Conservative floor
    if conservative > ltr_annual_net:
        floor_premium = conservative - ltr_annual_net
        sales_points.append(f"Even our conservative estimate beats rent by ${floor_premium:,.0f} — there's no downside")
    
    # Bathroom advantage
    if bathrooms >= bedrooms:
        sales_points.append(f"Your {bathrooms} bathrooms are a competitive advantage — guests pay premium for no queues")
    
    # BUILD FIT ASSESSMENT
    fit_warnings = []
    fit_score = "good"  # good, marginal, poor
    
    # Check if conservative beats LTR
    if conservative < ltr_annual_net:
        fit_warnings.append(f"Conservative estimate (${conservative:,.0f}) is below LTR net (${ltr_annual_net:,.0f}) — risk of underperforming")
        fit_score = "poor"
    
    # Check STR premium
    if str_premium_pct < 15:
        fit_warnings.append(f"STR premium only {str_premium_pct:.0f}% above LTR — may not justify extra management effort")
        if fit_score != "poor":
            fit_score = "marginal"
    
    # Check declining market
    if growth_rate < -0.05:
        fit_warnings.append(f"{region} market declining {abs(growth_rate)*100:.0f}% year-on-year — consider timing carefully")
        if fit_score != "poor":
            fit_score = "marginal"
    
    # Check low occupancy
    if avg_nights < 15:
        fit_warnings.append(f"Comparable properties averaging only {avg_nights:.0f} nights/month — weaker demand in this area")
        if fit_score != "poor":
            fit_score = "marginal"
    
    return {
        "conservative": conservative,
        "midrange": midrange,
        "optimistic": optimistic,
        "conservative_base": conservative_base,
        "midrange_base": midrange_base,
        "optimistic_base": optimistic_base,
        "growth_rate": growth_rate,
        "monthly_mid": monthly_mid,
        "monthly_high": monthly_high,
        "ltr_weekly": ltr_weekly,
        "ltr_annual": ltr_annual,
        "ltr_annual_net": ltr_annual_net,
        "ltr_monthly": ltr_monthly,
        "str_premium": str_premium,
        "str_premium_pct": str_premium_pct,
        "pool_adjustment": pool_adjustment,
        "pool_count": pool_count,
        "prospect_has_pool": prospect_has_pool,
        "advantages": advantages[:4],
        "disadvantages": disadvantages[:3],
        "sales_points": sales_points[:4],
        "top_comp": top_comp,
        "top_comp_annual": top_comp_annual,
        "min_pay": min_pay,
        "max_pay": max_pay,
        "avg_pay": avg_pay,
        "avg_nights": avg_nights,
        "fit_score": fit_score,
        "fit_warnings": fit_warnings
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
        growth = YOY_GROWTH.get(region, 0)
        growth_class = "growth-positive" if growth > 0 else "growth-negative"
        growth_arrow = "📈" if growth > 0 else "📉"
        
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
                🏠 <strong>${ltr_weekly}/week</strong> LTR<br>
                📈 <strong>+${str_premium:,.0f}</strong> STR premium<br><br>
                {growth_arrow} <span class="{growth_class}">{growth*100:+.1f}% YoY growth</span>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.caption("💡 Check [domain.com.au](https://www.domain.com.au/rent/) or [realestate.com.au](https://www.realestate.com.au/rent/) for LTR rates")
    
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
        
        # FIT ASSESSMENT
        if analysis['fit_score'] == "good":
            st.success("✅ **GOOD FIT** — This property shows strong STR potential")
        elif analysis['fit_score'] == "marginal":
            st.warning("⚠️ **MARGINAL FIT** — Review the considerations below before proceeding")
            for warning in analysis['fit_warnings']:
                st.caption(f"• {warning}")
        else:  # poor
            st.error("⛔ **PROCEED WITH CAUTION** — This property may not be a strong STR candidate")
            for warning in analysis['fit_warnings']:
                st.caption(f"• {warning}")
            st.caption("*Recommendation: Unless property has unique features not captured here, LTR may be safer.*")
        
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
        st.markdown("### 📊 Comparable Properties (Historical Performance)")
        
        for i, comp in enumerate(comps[:5], 1):
            annual = comp['avg_monthly_payout'] * 12
            amenities_lower = (comp.get('Amenities') or '').lower()
            has_pool = ('pool' in amenities_lower) and ('pool table' not in amenities_lower)
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
        
        # SEASONALITY CHART with smooth curves
        st.markdown("### 📈 Monthly Revenue Forecast (Year 1)")
        
        import plotly.graph_objects as go
        
        fig = go.Figure()
        
        # STR Optimistic (green)
        fig.add_trace(go.Scatter(
            x=MONTHS, y=analysis['monthly_high'],
            mode='lines',
            name='STR - Optimistic',
            line=dict(color='#10B981', width=3, shape='spline', smoothing=1.3),
            fill=None
        ))
        
        # STR Mid-range (blue)
        fig.add_trace(go.Scatter(
            x=MONTHS, y=analysis['monthly_mid'],
            mode='lines',
            name='STR - Mid-range',
            line=dict(color='#3B82F6', width=3, shape='spline', smoothing=1.3),
            fill=None
        ))
        
        # LTR (red dashed)
        fig.add_trace(go.Scatter(
            x=MONTHS, y=[analysis['ltr_monthly']] * 12,
            mode='lines',
            name='Long-term Rental',
            line=dict(color='#EF4444', width=2, dash='dash')
        ))
        
        fig.update_layout(
            xaxis_title=None,
            yaxis_title="Monthly Revenue ($)",
            yaxis_tickformat="$,.0f",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.2,
                xanchor="center",
                x=0.5
            ),
            margin=dict(l=0, r=0, t=20, b=60),
            height=400,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
        )
        
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#E5E7EB')
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#E5E7EB')
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Growth note
        if analysis['growth_rate'] != 0:
            growth_pct = analysis['growth_rate'] * 100
            if growth_pct > 0:
                st.success(f"📈 Projections include {growth_pct:.1f}% year-on-year market growth for {region}")
            else:
                st.warning(f"📉 Projections adjusted for {growth_pct:.1f}% year-on-year market change in {region}")
        
        # PROJECTED RETURNS
        growth_pct = analysis['growth_rate'] * 100
        growth_label = f" (adjusted for {growth_pct:+.0f}% market trend)" if growth_pct != 0 else ""
        st.markdown(f"### 💰 Projected Returns — Year 1 Forecast{growth_label}")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Conservative", f"${analysis['conservative']:,.0f}", 
                     help="Based on lowest comp, adjusted for market conditions")
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
            st.metric("LTR Annual (net of 6% fee)", f"${analysis['ltr_annual_net']:,.0f}")
        with col3:
            st.metric("STR Premium", f"+${analysis['str_premium']:,.0f}", 
                     f"{analysis['str_premium_pct']:.0f}% above LTR")
        
        if analysis['pool_adjustment'] < 1:
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
            <strong>STR vs LTR:</strong> +${analysis['str_premium']:,.0f} ({analysis['str_premium_pct']:.0f}% premium over ${analysis['ltr_annual_net']:,.0f} LTR net)<br>
            <strong>Market Occupancy:</strong> {analysis['avg_nights']:.0f} nights/month average<br>
            <strong>Market Trend:</strong> {analysis['growth_rate']*100:+.1f}% year-on-year
        </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
