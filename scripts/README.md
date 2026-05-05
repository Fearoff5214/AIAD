# Scripts

Utility and maintenance scripts for the Fearoff AIAD GST Compliance Platform.

| Script | Purpose |
|---|---|
| `bootstrap_primary_admin.py` | Seeds the primary admin account on first run |
| `debug_ocr.py` | Debug PaddleOCR pipeline output |
| `evaluate_model_metrics.py` | Run accuracy / F1-score evaluation on OCR models |
| `read_errors.py` | Parse and print Frappe error logs in readable format |
| `run_fearoff_aiad.bat` | Windows batch launcher for the full stack |
| `start_frappe_server.py` | Python helper to start the Frappe dev server |
| `verify_db.py` | Verify MariaDB schema and Portal Tenant records |

## tests/
Integration and functional tests — run from inside the Docker container.

```bash
docker exec fearoff_aiad-backend-1 python scripts/tests/test_all_features.py
```
