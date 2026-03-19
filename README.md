# Honey Homes Appraisal Agent

A Streamlit web app for generating STR property appraisals using real portfolio performance data.

## Features

- Enter prospect property details (address, beds, baths, features)
- Automatically pulls comparable properties from the Analytics DB
- Uses Claude AI to generate professional appraisals
- Includes projected returns (conservative/mid/optimistic)
- Generates talking points for owner conversations

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/aarontaylor-arch/honey-homes-portal.git
cd honey-homes-portal
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

Create a `.env` file or set these in your environment:

```
DB_SERVER=bnbme-fuse.database.windows.net
DB_USER=fuse
DB_PASSWORD=your_password_here
DB_NAME=fuseanalytics
ANTHROPIC_API_KEY=your_anthropic_api_key
```

### 4. Run locally

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501`

## Deploy to Azure App Service

### Option 1: Azure Portal

1. Create a new Web App in Azure Portal
2. Set runtime to Python 3.11
3. Connect to your GitHub repo
4. Add environment variables in Configuration > Application settings
5. Azure will auto-deploy on push

### Option 2: Azure CLI

```bash
az webapp up --name honey-homes-portal --resource-group Fuse-dev --runtime "PYTHON:3.11"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| DB_SERVER | Azure SQL server address |
| DB_USER | Database username |
| DB_PASSWORD | Database password |
| DB_NAME | Database name |
| ANTHROPIC_API_KEY | Claude API key |

## Security Notes

- Never commit credentials to the repo
- Use Azure Key Vault for production secrets
- Restrict database firewall once static IP is known
- Add Microsoft SSO for production (see `auth_example.py`)

## Future Modules

- Owner Performance Dashboard
- Guest Communications (via Guesty API)
- Operations & Cleaning
- Pricing Optimization
