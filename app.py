"""
Appraisal Tool
A Streamlit app for generating STR property appraisals using portfolio comps.
"""

import streamlit as st
import pymssql
import requests
import os
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
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
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
        l.AirbnbId,
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
        l.StreetAddress, l.AirbnbId, g.FirstName, g.LastName
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
# CLAUDE API FUNCTIONS
# =============================================================================

def generate_appraisal(property_details: dict, comps: list, region_averages: dict) -> str:
    """Use Claude to generate the appraisal summary."""
    
    if not ANTHROPIC_API_KEY:
        return "⚠️ Anthropic API key not configured. Set ANTHROPIC_API_KEY in environment variables."
    
    comps_text = ""
    for i, comp in enumerate(comps[:5], 1):
        annual_payout = (comp['avg_monthly_payout'] or 0) * 12
        annual_gross = (comp['avg_monthly_gross'] or 0) * 12
        avg_nights = comp['avg_nights'] or 0
        comps_text += f"""
Comp {i}: {comp['Nickname']}
- Bedrooms/Bathrooms: {comp['Bedrooms']}/{comp['Bathrooms']}
- Owner: {comp['OwnerName'] or 'Unknown'}
- Address: {comp['StreetAddress'] or 'Not listed'}
- Months of data: {comp['months_of_data']}
- Projected Annual Owner Payout: ${annual_payout:,.0f}
- Projected Annual Gross Revenue: ${annual_gross:,.0f}
- Average nights booked per month: {avg_nights:.0f}
- Amenities: {comp['Amenities'][:300] if comp['Amenities'] else 'Not listed'}...
"""
    
    prompt = f"""You are an STR Appraisal Agent. Generate a professional STR appraisal for a prospect property.

PROSPECT PROPERTY:
- Address: {property_details['address']}
- Region: {property_details['region']}
- Bedrooms: {property_details['bedrooms']}
- Bathrooms: {property_details['bathrooms']}
- Features: {property_details.get('features', 'Not specified')}
- Estimated Value: {property_details.get('value', 'Not specified')}

COMPARABLE PROPERTIES FROM OUR PORTFOLIO:
{comps_text}

Generate an appraisal with:

1. **PROPERTY SUMMARY** - Brief overview of the prospect

2. **COMPARABLE ANALYSIS** - How it stacks up against our portfolio comps

3. **PROJECTED RETURNS**
   - Conservative estimate (based on lowest performing similar comp)
   - Mid-range estimate (based on average of comps)
   - Optimistic estimate (based on top performer, if property has similar features)
   
4. **KEY CONSIDERATIONS**
   - Advantages this property has
   - Potential challenges or gaps vs top performers
   - Questions to ask the owner (usage expectations, renovation plans, etc.)

5. **TALKING POINTS FOR OWNER**
   - 3-4 bullet points the sales team can use in conversation
   - Focus on the value proposition vs long-term rental

Keep it concise and actionable. Use specific numbers from the comps.
"""
    
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-3-5-sonnet-20240229",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        else:
            return f"⚠️ API Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"⚠️ Error generating appraisal: {e}"


# =============================================================================
# MAIN APP
# =============================================================================

def main():
    st.markdown("# 🏠 Appraisal Tool")
    st.markdown("*Generate STR appraisals using real portfolio performance data*")
    st.markdown("---")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### Property Details")
        
        address = st.text_input(
            "Property Address",
            placeholder="e.g., 56 Kincaid St, Wagga Wagga NSW 2650"
        )
        
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            region = st.selectbox("Region", REGIONS)
        with col_b:
            bedrooms = st.number_input("Bedrooms", min_value=1, max_value=10, value=4)
        with col_c:
            bathrooms = st.number_input("Bathrooms", min_value=1, max_value=10, value=2)
        
        features = st.text_area(
            "Property Features",
            placeholder="e.g., Modern renovation, pool, shed, close to CBD...",
            height=100
        )
        
        value = st.text_input(
            "Estimated Property Value (optional)",
            placeholder="e.g., $750,000"
        )
    
    with col2:
        st.markdown("### Quick Stats")
        st.markdown(f"**Region:** {region}")
        
        averages = get_region_averages(region)
        if bedrooms in averages:
            avg = averages[bedrooms]
            annual_payout = (avg['avg_monthly_payout'] or 0) * 12
            avg_nights = avg['avg_nights'] or 0
            st.markdown(f"""
            <div class="metric-card">
                <strong>{bedrooms}-bed average in {region}</strong><br>
                📊 {avg['property_count']} properties<br>
                💰 ${annual_payout:,.0f}/year owner payout<br>
                🛏️ {avg_nights:.0f} nights/month
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info(f"No {bedrooms}-bed data for {region}")
    
    st.markdown("---")
    
    if st.button("🔍 Generate Appraisal", use_container_width=True):
        if not address:
            st.warning("Please enter a property address.")
            return
        
        with st.spinner("Finding comparable properties..."):
            comps = get_regional_comps(region, bedrooms)
        
        if not comps:
            st.warning(f"No comparable properties found in {region} with {bedrooms}±1 bedrooms.")
            return
        
        st.markdown("### 📊 Comparable Properties")
        
        comp_data = []
        for comp in comps[:5]:
            annual_payout = (comp['avg_monthly_payout'] or 0) * 12
            annual_gross = (comp['avg_monthly_gross'] or 0) * 12
            comp_data.append({
                "Property": comp['Nickname'],
                "Owner": comp['OwnerName'] or 'Unknown',
                "Beds": comp['Bedrooms'],
                "Baths": comp['Bathrooms'],
                "Months Data": comp['months_of_data'],
                "Annual Payout": f"${annual_payout:,.0f}",
                "Annual Gross": f"${annual_gross:,.0f}"
            })
        
        st.table(comp_data)
        
        st.markdown("### 📝 Appraisal Summary")
        
        with st.spinner("Generating appraisal with Claude..."):
            property_details = {
                "address": address,
                "region": region,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "features": features,
                "value": value
            }
            
            appraisal = generate_appraisal(property_details, comps, averages)
        
        st.markdown(appraisal)
        
        st.markdown("---")
        st.download_button(
            label="📥 Download Appraisal",
            data=appraisal,
            file_name=f"appraisal_{address.replace(' ', '_').replace(',', '')}_{datetime.now().strftime('%Y%m%d')}.txt",
            mime="text/plain"
        )


if __name__ == "__main__":
    main()
