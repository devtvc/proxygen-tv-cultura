-- Initialize database for broadcast proxy system
-- This file is executed automatically by the postgres container on first start

-- The actual table creation will be handled by SQLAlchemy/Alembic migrations
-- This file ensures the database is ready and can be used for testing connections

SELECT 'Database initialization complete' as message;