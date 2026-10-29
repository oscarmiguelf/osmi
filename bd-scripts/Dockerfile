# PostgreSQL with the schema baked in: on its FIRST start (empty volume) it creates every table, the catalogs,
# the admin user, one branch and one register. Later starts reuse the volume and run nothing.
FROM postgres:18-alpine
COPY all_in_one_schema.sql /docker-entrypoint-initdb.d/10-schema.sql
COPY first-setup.sh /docker-entrypoint-initdb.d/20-first-setup.sh
# .txt: the entrypoint only runs *.sql / *.sh by itself; first-setup.sh runs it with the role's password
COPY app-role.sql /docker-entrypoint-initdb.d/app-role.sql.txt
