#!/bin/sh
# Runs once, right after the schema (docker-entrypoint-initdb.d, empty volume only).
# The schema seeds admin/admin, "Test Branch" and "Register 1"; here they get the real values from the environment.
set -eu
: "${ADMIN_PASSWORD:?Set ADMIN_PASSWORD: the admin's first password (they must change it when they log in)}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v admin_password="$ADMIN_PASSWORD" \
  -v branch_name="${BRANCH_NAME:-Matriz}" \
  -v branch_code="${BRANCH_CODE:-SUC1}" \
  -v register_name="${REGISTER_NAME:-Caja 1}" <<'SQL'
UPDATE users
   SET password_hash = crypt(:'admin_password', gen_salt('bf', 12)), must_change_password = TRUE
 WHERE LOWER(email) = 'admin';

UPDATE branches
   SET name = :'branch_name', code = UPPER(:'branch_code'), phone = NULL, address = NULL
 WHERE code = 'SUC1';

UPDATE cash_registers SET name = :'register_name' WHERE name = 'Register 1';
SQL

# The API connects as osmi_app, not as the owner (a superuser in this image): it can read and write data, but can't
# alter or drop tables, disable triggers (the business rules), create roles or reach other databases.
: "${APP_DB_PASSWORD:?Set APP_DB_PASSWORD: password of the osmi_app role the API connects with}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_DB_PASSWORD" -v db="$POSTGRES_DB" -v owner="$POSTGRES_USER" -f /docker-entrypoint-initdb.d/app-role.sql.txt
