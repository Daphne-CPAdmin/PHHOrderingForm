# Component Usage Guide

## Quick Start

### Fetch Current Orders

**Run the component:**
```bash
python components/fetch_current_orders.py
```

**Or run the full workflow:**
```bash
python workflow.py
```

**Output:**
- `data/output/current_orders.csv` - All current orders
- `data/temp/orders_snapshot_YYYYMMDD_HHMMSS.csv` - Timestamped snapshot
- `logs/audit_log.txt` - Detailed logs

## Environment Variables Required

Make sure these are set in Railway (or `.env` file for local testing):

```
GOOGLE_SHEETS_ID=18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s
GOOGLE_CREDENTIALS_JSON=<your entire credentials.json content>
```

## What the Component Does

1. Connects to Google Sheets using credentials
2. Reads from "PepHaul Entry" worksheet
3. Extracts all order data
4. Saves to CSV file with timestamped snapshot
5. Logs summary (order count, status breakdown, etc.)

## Adding More Components

To add new automation components:

1. Create new file in `components/` directory
2. Follow the template pattern (see `components/fetch_current_orders.py`)
3. Add import and step to `workflow.py`
4. Test independently first, then add to workflow

## Daily Updates

Run `python workflow.py` daily to:
- Fetch latest orders
- Generate snapshots
- Update reports

Safe to run multiple times - won't create duplicates!

