"""
Appraisal Tool v2
A Streamlit app for generating STR property appraisals using portfolio comps.
Includes LTR comparison, property lookup, and PDF output.
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

# LTR weekly rental estimates by region and bedrooms (conservative estimates)
LTR_ESTIMATES = {
    "Wagga Wagga": {2: 380, 3: 450, 4: 550, 5: 650},
    "Orange": {2: 350, 3: 420, 4: 500, 5: 600},
    "Bathurst": {2: 360, 3: 430, 4: 520, 5: 620},
    "Dubbo": {2: 340, 3: 400, 4: 480, 5: 580},
}

# Amenity premium/discount factors
AMENITY_FACTORS = {
    "pool": 1.15,  # 15% premium
    "spa": 1.10,
    "pet friendly": 1.08,
    "air conditioning": 1.05,
    "fireplace": 1.05,
    "garage": 1.03,
    "no pool": 0.90,  # 10% discount if comps have pools but prospect doesn't
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
    
    .comparison-table {
        background: white;
        border-radius: 12px;
        padding: 1rem;
        margin: 1rem 0;
    }
    
    .highlight-box {
        background: linear-gradient(135deg, #DBEAFE 0%, #BFDBFE 100%);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
    }
    
    .warning-box {
        background: #FEF3C7;
        border-left: 4px solid #F59E0B;
        padding: 1rem;
        border-radius: 0 8px 8px 0;
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
# AMENITY ANALYSIS
# =============================================================================

def analyze_amenities(prospect_features: str, comps: list) -> dict:
    """Analyze amenities and calculate adjustment factor."""
    prospect_lower = prospect_features.lower() if prospect_features else ""
    
    # Check prospect amenities
    prospect_has_pool = "pool" in prospect_lower
    prospect_has_spa = "spa" in prospect_lower or "hot tub" in prospect_lower
    prospect_pets = "pet" in prospect_lower
    
    # Check what comps have
    comp_pools = 0
    for comp in comps[:5]:
        if comp['Amenities'] and 'pool' in comp['Amenities'].lower():
            comp_pools += 1
    
    # Calculate adjustment factor
    factor = 1.0
    notes = []
    
    if prospect_has_pool:
        factor *= AMENITY_FACTORS["pool"]
        notes.append("✓ Pool adds ~15% premium")
    elif comp_pools >= 2:
        factor *= AMENITY_FACTORS["no pool"]
        notes.append("⚠ No pool vs comps with pools (-10%)")
    
    if prospect_has_spa:
        factor *= AMENITY_FACTORS["spa"]
        notes.append("✓ Spa/hot tub adds ~10% premium")
    
    if prospect_pets:
        factor *= AMENITY_FACTORS["pet friendly"]
        notes.append("✓ Pet-friendly adds ~8% premium")
    
    return {
        "factor": factor,
        "notes": notes,
        "prospect_has_pool": prospect_has_pool,
        "comp_pools": comp_pools
    }


# =============================================================================
# LTR COMPARISON
# =============================================================================

def get_ltr_estimate(region: str, bedrooms: int) -> dict:
    """Get long-term rental estimate for comparison."""
    weekly = LTR_ESTIMATES.get(region, {}).get(bedrooms, 450)
    annual = weekly * 52
    
    return {
        "weekly": weekly,
        "annual": annual,
        "source": "Regional market average"
    }


# =============================================================================
# CLAUDE API FUNCTIONS
# =============================================================================

def generate_appraisal(property_details: dict, comps: list, region_averages: dict, 
                       ltr_estimate: dict, amenity_analysis: dict) -> str:
    """Use Claude to generate the appraisal summary."""
    
    if not ANTHROPIC_API_KEY:
        return "⚠️ Anthropic API key not configured. Set ANTHROPIC_API_KEY in environment variables."
    
    # Build comps text
    comps_text = ""
    payout_values = []
    for i, comp in enumerate(comps[:5], 1):
        annual_payout = (comp['avg_monthly_payout'] or 0) * 12
        annual_gross = (comp['avg_monthly_gross'] or 0) * 12
        avg_nights = comp['avg_nights'] or 0
        payout_values.append(annual_payout)
        
        has_pool = "Yes" if comp['Amenities'] and 'pool' in comp['Amenities'].lower() else "No"
        
        comps_text += f"""
Comp {i}: {comp['Nickname']}
- Bedrooms/Bathrooms: {comp['Bedrooms']}/{comp['Bathrooms']}
- Owner: {comp['OwnerName'] or 'Unknown'}
- Pool: {has_pool}
- Months of data: {comp['months_of_data']}
- Annual Owner Payout: ${annual_payout:,.0f}
- Annual Gross Revenue: ${annual_gross:,.0f}
- Average nights booked per month: {avg_nights:.0f}
"""
    
    # Calculate ranges based on actual comp data
    if payout_values:
        min_payout = min(payout_values)
        max_payout = max(payout_values)
        avg_payout = sum(payout_values) / len(payout_values)
    else:
        min_payout = max_payout = avg_payout = 0
    
    # Apply amenity adjustment
    adjustment = amenity_analysis['factor']
    
    prompt = f"""You are an STR Appraisal Agent. Generate a professional, CONSERVATIVE appraisal for a prospect property.

CRITICAL INSTRUCTIONS:
1. Be CONSERVATIVE with estimates - it's better to under-promise and over-deliver
2. Consider that comps may have advantages the prospect doesn't (location, fit-out quality, reviews)
3. New properties take 3-6 months to build reviews and optimise pricing
4. Include the LTR comparison as a key decision factor for the owner

PROSPECT PROPERTY:
- Address: {property_details['address']}
- Region: {property_details['region']}
- Bedrooms: {property_details['bedrooms']}
- Bathrooms: {property_details['bathrooms']}
- Features: {property_details.get('features', 'Not specified')}
- Estimated Value: {property_details.get('value', 'Not specified')}

COMPARABLE PROPERTIES FROM OUR PORTFOLIO:
{comps_text}

COMP STATISTICS:
- Lowest annual payout: ${min_payout:,.0f}
- Highest annual payout: ${max_payout:,.0f}
- Average annual payout: ${avg_payout:,.0f}
- Amenity adjustment factor: {adjustment:.2f}

LONG-TERM RENTAL COMPARISON:
- Weekly LTR estimate: ${ltr_estimate['weekly']}/week
- Annual LTR estimate: ${ltr_estimate['annual']:,}/year

AMENITY NOTES:
{chr(10).join(amenity_analysis['notes']) if amenity_analysis['notes'] else 'No significant amenity adjustments'}

Generate an appraisal with these EXACT sections:

**1. PROPERTY SUMMARY**
Brief overview - 2-3 sentences max.

**2. COMPARABLE PROPERTIES**
List the top 3-4 most relevant comps with their annual payouts.

**3. PROJECTED RETURNS**

Present in this exact table format:
| Management Type | Weekly | Annual | Notes |
|-----------------|--------|--------|-------|
| Short-Term Rental | $X - $Y | $XX,XXX - $YY,YYY | Based on [X] comps |
| Long-Term Rental | ${ltr_estimate['weekly']} | ${ltr_estimate['annual']:,} | Current market |
| **STR Premium** | +$Z | +$ZZ,ZZZ | X% above LTR |

Then show scenarios:
- Conservative: Based on lowest comp MINUS 10% for new property ramp-up
- Mid-range: Based on average of comps
- Optimistic: Only achievable if property matches top performer amenities/location

**4. KEY CONSIDERATIONS**
- What advantages does this property have?
- What gaps exist vs top performers?
- Questions to ask the owner

**5. CONVERSION FLAGS FOR SALES STAFF**
List 2-3 specific objection handlers based on this property.

**6. TALKING POINTS FOR OWNER**
3-4 bullet points ready to use in conversation. Always lead with the STR vs LTR comparison.

Keep the total response under 800 words. Be specific with numbers from the comps.
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
                "model": "claude-sonnet-4-20250514",
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
    st.markdown("*Generate STR appraisals with LTR comparison*")
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
            placeholder="e.g., Pool, modern renovation, shed, close to CBD, pet friendly...",
            height=100
        )
        
        value = st.text_input(
            "Estimated Property Value (optional)",
            placeholder="e.g., $750,000"
        )
    
    with col2:
        st.markdown("### Quick Stats")
        st.markdown(f"**Region:** {region}")
        
        # Get LTR estimate
        ltr = get_ltr_estimate(region, bedrooms)
        
        averages = get_region_averages(region)
        if bedrooms in averages:
            avg = averages[bedrooms]
            annual_payout = (avg['avg_monthly_payout'] or 0) * 12
            avg_nights = avg['avg_nights'] or 0
            str_premium = annual_payout - ltr['annual']
            str_premium_pct = (str_premium / ltr['annual'] * 100) if ltr['annual'] > 0 else 0
            
            st.markdown(f"""
            <div class="metric-card">
                <strong>{bedrooms}-bed in {region}</strong><br>
                📊 {avg['property_count']} properties in portfolio<br>
                💰 ${annual_payout:,.0f}/year STR payout<br>
                🏠 ${ltr['annual']:,}/year LTR estimate<br>
                📈 <strong>+${str_premium:,.0f} STR premium ({str_premium_pct:.0f}%)</strong>
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
        
        # Get LTR estimate
        ltr_estimate = get_ltr_estimate(region, bedrooms)
        
        # Analyze amenities
        amenity_analysis = analyze_amenities(features, comps)
        
        # Display comps
        st.markdown("### 📊 Comparable Properties")
        
        comp_data = []
        for comp in comps[:5]:
            annual_payout = (comp['avg_monthly_payout'] or 0) * 12
            annual_gross = (comp['avg_monthly_gross'] or 0) * 12
            has_pool = "✓" if comp['Amenities'] and 'pool' in comp['Amenities'].lower() else ""
            comp_data.append({
                "Property": comp['Nickname'],
                "Owner": comp['OwnerName'] or 'Unknown',
                "Beds": comp['Bedrooms'],
                "Baths": comp['Bathrooms'],
                "Pool": has_pool,
                "Months Data": comp['months_of_data'],
                "Annual Payout": f"${annual_payout:,.0f}",
                "Annual Gross": f"${annual_gross:,.0f}"
            })
        
        st.table(comp_data)
        
        # Display LTR comparison box
        st.markdown(f"""
        <div class="highlight-box">
            <strong>📈 Long-Term Rental Comparison</strong><br>
            Estimated LTR for {bedrooms}-bed in {region}: <strong>${ltr_estimate['weekly']}/week</strong> (${ltr_estimate['annual']:,}/year)
        </div>
        """, unsafe_allow_html=True)
        
        # Display amenity notes if any
        if amenity_analysis['notes']:
            st.markdown("### 🏊 Amenity Analysis")
            for note in amenity_analysis['notes']:
                st.markdown(f"- {note}")
        
        # Generate AI appraisal
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
            
            appraisal = generate_appraisal(
                property_details, comps, averages, 
                ltr_estimate, amenity_analysis
            )
        
        st.markdown(appraisal)
        
        st.markdown("---")
        
        # Download as markdown (cleaner than txt)
        st.download_button(
            label="📥 Download Appraisal",
            data=appraisal,
            file_name=f"appraisal_{address.replace(' ', '_').replace(',', '')}_{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown"
        )


if __name__ == "__main__":
    main()
