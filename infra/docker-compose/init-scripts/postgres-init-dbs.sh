#!/bin/bash
# Create multiple PostgreSQL databases on first run
set -e

create_db() {
    local database=$1
    echo "Creating database: $database"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
        CREATE DATABASE $database;
        GRANT ALL PRIVILEGES ON DATABASE $database TO $POSTGRES_USER;
EOSQL
}

for db in mlflow airflow feast; do
    if psql -lqt --username "$POSTGRES_USER" | cut -d \| -f 1 | grep -qw "$db"; then
        echo "Database $db already exists, skipping"
    else
        create_db "$db"
    fi
done
