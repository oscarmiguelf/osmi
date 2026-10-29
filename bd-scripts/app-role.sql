-- Least-privilege role for the API (run as the database owner). Variables: app_password, db, owner.
--   psql -v app_password='...' -v db=osmi -v owner=osmi -f app-role.sql
SELECT 'CREATE ROLE osmi_app' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'osmi_app') \gexec
ALTER ROLE osmi_app WITH LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO osmi_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO osmi_app;

-- Data only (no TRUNCATE, REFERENCES, TRIGGER or ownership)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO osmi_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO osmi_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO osmi_app;

-- Tables, sequences and functions created later by the owner (schema changes) get the same rights
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO osmi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO osmi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO osmi_app;
