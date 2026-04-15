$env:DB_HOST="192.168.10.5"
$env:DB_USER="root"
$env:DB_PASSWORD="unde5466"
$env:DB_NAME="rcs_db"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
